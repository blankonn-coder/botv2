import time
import random
import requests
import pandas as pd
import ta

# --- 1. CONFIGURATION & FETCH PAIRS ---
def get_bybit_pairs(session):
    url = "https://api.bybit.com/v5/market/tickers?category=spot"
    try:
        resp = session.get(url, timeout=10).json()
        if resp.get("retCode") == 0:
            list_data = resp["result"]["list"]
            symbols = [item["symbol"] for item in list_data if item["symbol"].endswith("USDT")]
            return set(symbols)
    except Exception as e:
        print(f"[WARN] Gagal mengambil data Bybit: {e}")
    return set()

def get_binance_usdt_pairs(session):
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        resp = session.get(url, timeout=10).json()
        pairs = []
        for item in resp:
            symbol = item["symbol"]
            # Ambil pair USDT, hindari leveraged/stablecoins
            if symbol.endswith("USDT") and not any(x in symbol for x in ["UPUSDT", "DOWNUSDT", "BUSD", "FDUSD", "TUSD", "USDC"]):
                pairs.append({
                    "symbol": symbol,
                    "volume_usd": float(item["quoteVolume"]),
                    "price_change": float(item["priceChangePercent"])
                })
        return pairs
    except Exception as e:
        print(f"[ERROR] Gagal mengambil data Binance Tickers: {e}")
        return []

# --- 2. SCALPING TECHNICAL ANALYSIS & WHALE DETECTION ---
def analyze_coin(symbol, session):
    # Fetch 7 hari data kandel 15m -> 7 * 24 * 4 = 672 kandel (limit 700)
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=15m&limit=700"
    try:
        resp = session.get(url, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if len(data) < 200:
            return None
        
        # Format Data Frame
        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore"
        ])
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)

        # 1. RSI (14)
        rsi_series = ta.momentum.rsi(df["close"], window=14)
        latest_rsi = rsi_series.iloc[-1]

        # Filter RSI fleksibel (30 - 70)
        if pd.isna(latest_rsi) or not (30 <= latest_rsi <= 70):
            return None

        # 2. EMA Scalping (EMA 9 & EMA 21)
        df["ema9"] = ta.trend.ema_indicator(df["close"], window=9)
        df["ema21"] = ta.trend.ema_indicator(df["close"], window=21)
        latest_ema9 = df["ema9"].iloc[-1]
        latest_ema21 = df["ema21"].iloc[-1]
        ema_bullish = latest_ema9 > latest_ema21

        # 3. Bollinger Bands (20, 2)
        bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
        latest_bb_lower = bb.bollinger_lband().iloc[-1]

        # 4. Stochastic RSI (14, 3, 3)
        stoch_rsi_k = ta.momentum.stochrsi_k(df["close"], window=14, smooth1=3, smooth2=3) * 100
        stoch_rsi_d = ta.momentum.stochrsi_d(df["close"], window=14, smooth1=3, smooth2=3) * 100
        stoch_k = stoch_rsi_k.iloc[-1] if not pd.isna(stoch_rsi_k.iloc[-1]) else 50.0
        stoch_d = stoch_rsi_d.iloc[-1] if not pd.isna(stoch_rsi_d.iloc[-1]) else 50.0

        # 5. Deteksi Whale Activity (Volume Spike)
        df["vol_sma"] = df["volume"].rolling(window=20).mean()
        last_vol = df["volume"].iloc[-1]
        avg_vol = df["vol_sma"].iloc[-1]
        
        is_whale_present = False
        whale_score_bonus = 0.0
        if avg_vol > 0 and (last_vol >= 2.0 * avg_vol):
            is_whale_present = True
            whale_score_bonus = 2.0

        # 6. Pola Candlestick Scalping (Hammer / Engulfing)
        last_open = df["open"].iloc[-1]
        last_close = df["close"].iloc[-1]
        last_high = df["high"].iloc[-1]
        last_low = df["low"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        prev_open = df["open"].iloc[-2]

        is_bullish_engulfing = (prev_close < prev_open) and (last_close > last_open) and (last_close > prev_open) and (last_open < prev_close)
        body = abs(last_close - last_open)
        lower_wick = min(last_open, last_close) - last_low
        is_hammer = (lower_wick >= 2 * body) and (body > 0)

        # Hitung Volatilitas & Rating (Skala 1-10)
        last_price = df["close"].iloc[-1]
        volatility_7d = ((df["high"].tail(672).max() - df["low"].tail(672).min()) / last_price) * 100

        base_rate = 5.0
        if 30 <= latest_rsi <= 45:
            base_rate += 1.5
        elif 45 < latest_rsi <= 60:
            base_rate += 0.5

        if ema_bullish:
            base_rate += 1.0

        if last_price <= latest_bb_lower * 1.005:
            base_rate += 1.0

        if is_bullish_engulfing or is_hammer:
            base_rate += 1.0

        if stoch_k < 30 and stoch_d < 30:
            base_rate += 0.5

        final_rate = min(10.0, base_rate + whale_score_bonus)

        # Parameter Trade Scalping
        entry_price = last_price * 1.001  # Slippage Binance/Bybit ~0.1%
        tp_percent = 3.0 if final_rate >= 8.0 else 2.0
        sl_percent = 1.0 if final_rate >= 8.0 else 1.5

        take_profit = entry_price * (1 + (tp_percent / 100))
        stop_loss = entry_price * (1 - (sl_percent / 100))

        # Rangkuman Indikator Scalping
        scalping_signals = []
        if ema_bullish: scalping_signals.append("EMA 9 > EMA 21 (Bullish Trend)")
        if last_price <= latest_bb_lower * 1.005: scalping_signals.append("Near Lower BB")
        if stoch_k < 30: scalping_signals.append(f"StochRSI Oversold (K:{stoch_k:.1f})")
        if is_bullish_engulfing: scalping_signals.append("Bullish Engulfing")
        if is_hammer: scalping_signals.append("Hammer Pattern")

        return {
            "symbol": symbol,
            "price": last_price,
            "entry_price": entry_price,
            "rsi": round(latest_rsi, 2),
            "stoch_k": round(stoch_k, 1),
            "stoch_d": round(stoch_d, 1),
            "ema_signal": "BULLISH (EMA9 > EMA21)" if ema_bullish else "NEUTRAL/BEARISH",
            "whale_detected": "YA (Spike Volume)" if is_whale_present else "TIDAK",
            "signals": ", ".join(scalping_signals) if scalping_signals else "Standar Accumulation",
            "rate": round(final_rate, 1),
            "tp": round(take_profit, 6),
            "sl": round(stop_loss, 6),
            "tp_pct": tp_percent,
            "sl_pct": sl_percent,
            "volatility_7d": round(volatility_7d, 2)
        }

    except Exception:
        return None

# --- 3. MAIN WORKFLOW ---
def main():
    print("="*85)
    print("   BOT SCOUTING CRYPTO SCALPING (15M / 7-DAY CANDLE) - BINANCE / BYBIT SCANNER")
    print("="*85)

    session = requests.Session()

    print("[1/4] Mengambil daftar pair dari Bybit...")
    bybit_pairs = get_bybit_pairs(session)
    print(f"      Total pair Bybit terdeteksi: {len(bybit_pairs)}")

    print("[2/4] Mengambil daftar pair USDT dari Binance...")
    all_binance_pairs = get_binance_usdt_pairs(session)
    print(f"      Total pair Binance terdeteksi: {len(all_binance_pairs)}")

    # Acak dan ambil maksimal 300 koin
    random.shuffle(all_binance_pairs)
    scanned_pool = all_binance_pairs[:300]
    print(f"[3/4] Melakukan random sampling pada {len(scanned_pool)} koin...")

    results = []
    print("[4/4] Analisis Indikator Scalping (RSI, EMA, BB, StochRSI, Whale Volume)...")
    
    for idx, coin in enumerate(scanned_pool):
        symbol = coin["symbol"]
        
        # Cross-check ketersediaan pair di Bybit (bila data tersedia)
        is_in_bybit = symbol in bybit_pairs if bybit_pairs else True

        # Analisis Teknikal Scalping
        analysis = analyze_coin(symbol, session)
        if analysis:
            analysis["24h_vol_usd"] = coin["volume_usd"]
            analysis["24h_change"] = coin["price_change"]
            analysis["bybit_status"] = "MATCHED (Tersedia)" if is_in_bybit else "BINANCE ONLY"
            results.append(analysis)

        time.sleep(0.05)

    # Urutkan berdasarkan Rating tertinggi
    results = sorted(results, key=lambda x: x["rate"], reverse=True)

    # --- REPORT PRINTING ---
    print("
" + "="*85)
    print(f" HASIL LAPORAN SCOUTING SCALPING (Total Lolos Filter: {len(results)})")
    print("="*85)

    if not results:
        print("Tidak ada koin yang memenuhi kriteria pada run kali ini.")
        return

    for item in results:
        print(f"► PAIR KOIN          : {item['symbol']}")
        print(f"  Exchange Status    : Binance (Main) | Bybit: {item['bybit_status']}")
        print(f"  Harga Pasar        : {item['price']}")
        print(f"  Est. Open Position : {item['entry_price']} (Toleransi Slippage ~0.1%)")
        print(f"  RSI (14 - 15M)     : {item['rsi']} (Rentang 30 - 70)")
        print(f"  StochRSI (K/D)     : {item['stoch_k']} / {item['stoch_d']}")
        print(f"  Tren EMA Scalping  : {item['ema_signal']}")
        print(f"  Sinyal Tambahan    : {item['signals']}")
        print(f"  Pergerakan Whale   : {item['whale_detected']}")
        print(f"  Volatilitas 7 Hari : {item['volatility_7d']}%")
        print(f"  Perubahan 24 Jam   : {item['24h_change']}% | Vol 24h: ${item['24h_vol_usd']:,.0f}")
        print(f"  RATING ANALISIS    : {item['rate']} / 10.0")
        print(f"  Target Take Profit : {item['tp']} (+{item['tp_pct']}%)")
        print(f"  Target Stop Loss   : {item['sl']} (-{item['sl_pct']}%)")
        print("-" * 85)

if __name__ == "__main__":
    main()

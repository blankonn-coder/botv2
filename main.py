import os
import logging
import requests
import pandas as pd
import ta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ==========================================
# KONFIGURASI BOT (DILONGGARKAN & DIOPTIMALKAN)
# ==========================================
DATA_SOURCE = "AUTO"          # "AUTO", "BINANCE", "BYBIT"
MIN_TURNOVER_24H = 50000      # Dilonggarkan ke $50.000 agar koin awal momentum tidak terbuang
MIN_RSI = 25                  # Range RSI diperluas (25 - 75)
MAX_RSI = 75
PASSING_SCORE = 50            # Threshold skor passing grade dilonggarkan ke 50%

BINANCE_REST_24HR = "https://api.binance.com/api/v3/ticker/24hr"
BYBIT_REST_24HR = "https://api.bybit.com/v5/market/tickers"
COINGECKO_MARKETS_API = "https://api.coingecko.com/api/v3/coins/markets"

def fetch_market_data():
    """Mengambil data pasar secara cepat dan menggabungkannya"""
    logging.info(f"[STEP 1] Fetching Market Data (Min Turnover: ${MIN_TURNOVER_24H:,.0f})...")
    market_map = {}

    # 1. Binance
    if DATA_SOURCE in ["BINANCE", "AUTO"]:
        try:
            res = requests.get(BINANCE_REST_24HR, timeout=5).json()
            for t in res:
                pair = t.get('symbol', '')
                if pair.endswith("USDT") and not any(x in pair for x in ["UPUSDT", "DOWNUSDT", "BEAR", "BULL"]):
                    vol_24h = float(t.get('quoteVolume', 0))
                    price = float(t.get('lastPrice', 0))
                    if vol_24h >= MIN_TURNOVER_24H and price > 0:
                        sym = pair.replace("USDT", "")
                        market_map[sym] = {"symbol": sym, "pair": pair, "price": price, "volume_24h": vol_24h, "source": "Binance"}
        except Exception as e:
            logging.error(f"Error fetching Binance: {e}")

    # 2. Bybit (Fallback / Additional)
    if DATA_SOURCE in ["BYBIT", "AUTO"] and (not market_map or DATA_SOURCE == "BYBIT"):
        try:
            res = requests.get(f"{BYBIT_REST_24HR}?category=spot", timeout=5).json()
            if res.get("retCode") == 0:
                for t in res.get("result", {}).get("list", []):
                    pair = t.get('symbol', '')
                    if pair.endswith("USDT"):
                        vol_24h = float(t.get('turnover24h', 0))
                        price = float(t.get('lastPrice', 0))
                        sym = pair.replace("USDT", "")
                        if vol_24h >= MIN_TURNOVER_24H and price > 0 and sym not in market_map:
                            market_map[sym] = {"symbol": sym, "pair": pair, "price": price, "volume_24h": vol_24h, "source": "Bybit"}
        except Exception as e:
            logging.error(f"Error fetching Bybit: {e}")

    logging.info(f"[STEP 1 PASSED] {len(market_map)} pairs match liquidity criteria.")
    return list(market_map.values())

def filter_rsi_and_momentum(coins):
    """Filter RSI Fleksibel & Perhitungan Indikator"""
    logging.info(f"[STEP 2] Screening RSI ({MIN_RSI} - {MAX_RSI})...")
    passed_coins = []
    
    # Sort berdasarkan volume dan ambil top 100 koin
    sorted_coins = sorted(coins, key=lambda x: x['volume_24h'], reverse=True)[:100]

    for c in sorted_coins:
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={c['pair']}&interval=1h&limit=30"
            res = requests.get(url, timeout=2).json()
            if isinstance(res, list) and len(res) >= 15:
                closes = [float(k[4]) for k in res]
                df = pd.DataFrame({"close": closes})
                
                rsi_series = ta.momentum.RSIIndicator(close=df["close"], window=14).rsi()
                current_rsi = float(rsi_series.iloc[-1])

                if MIN_RSI <= current_rsi <= MAX_RSI:
                    c["rsi"] = round(current_rsi, 2)
                    passed_coins.append(c)
        except Exception:
            pass

    logging.info(f"[STEP 2 PASSED] {len(passed_coins)} coins passed RSI screening.")
    return passed_coins

def analyze_whale_and_score(coin):
    """Sistem Grading Serba Cepat dan Ringan"""
    score = 50  # Base Score Lolos Step 1 & Step 2
    detected_info = []

    # Bonus RSI Optimal Zone
    if 40 <= coin['rsi'] <= 60:
        score += 20
    elif 30 <= coin['rsi'] < 40 or 60 < coin['rsi'] <= 70:
        score += 10

    # Volume Turnover Whale Check
    if coin['volume_24h'] >= 1000000:
        score += 20
        detected_info.append(f"High Turnover (${coin['volume_24h']:,.0f})")
    elif coin['volume_24h'] >= 300000:
        score += 10
        detected_info.append("Moderate Capital Inflow")

    if not detected_info:
        detected_info.append("Standard Flow")

    return score, ", ".join(detected_info)

def send_telegram_alert(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=3)
        except Exception as e:
            logging.error(f"Failed to send Telegram alert: {e}")

def run_scouting_bot():
    logging.info("========== STARTING CRYPTO SCOUTING BOT V7 ==========")
    
    # Step 1: Market Fetching
    candidate_coins = fetch_market_data()
    
    # Step 2: RSI Screening
    step2_coins = filter_rsi_and_momentum(candidate_coins)
    
    # Step 3 & 4: Scoring & Execution
    qualified_signals = []
    for c in step2_coins:
        score, whale_info = analyze_whale_and_score(c)
        
        if score >= PASSING_SCORE:
            c['score'] = score
            c['detected_whale'] = whale_info
            c['stop_loss'] = round(c['price'] * 0.98, 6)
            c['take_profit'] = round(c['price'] * 1.05, 6)
            qualified_signals.append(c)

    logging.info(f"========== SCOUTING COMPLETED: FOUND {len(qualified_signals)} QUALIFIED SIGNALS ==========")
    
    for sig in qualified_signals:
        alert_msg = (
            "🎯 *SCOUTING BOT SIGNAL DETECTED* 🎯\n\n"
            f"• *Coin:* `{sig['pair']}` ({sig['source']})\n"
            f"• *Entry Price:* `${sig['price']}`\n"
            f"• *Volume 24h:* `${sig['volume_24h']:,.2f}`\n"
            f"• *RSI (1H):* `{sig['rsi']}`\n"
            f"• *Grading Score:* `{sig['score']}%`\n"
            f"• *Whale Status:* `{sig['detected_whale']}`\n\n"
            "🛡 *Risk Management:*\n"
            f"• *Stop Loss (2%):* `${sig['stop_loss']}`\n"
            f"• *Take Profit (5%):* `${sig['take_profit']}`"
        )
        print(alert_msg)
        print("-" * 50)
        send_telegram_alert(alert_msg)

if __name__ == "__main__":
    run_scouting_bot()

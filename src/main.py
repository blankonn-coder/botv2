import time
import json
import logging
import os
import requests
import pandas as pd
import ta
import websocket

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BINANCE_REST_24HR = "https://api.binance.com/api/v3/ticker/24hr"
COINGECKO_MARKETS_API = "https://api.coingecko.com/api/v3/coins/markets"
DIA_ORACLE_API = "https://api.diadata.org/v1/quotation"
COINLOBSTER_CRYPTO_WHALES = "https://coinlobster.com/api/public/crypto-whales"

def fetch_coingecko_gems():
    """Mengambil daftar koin gems dari CoinGecko dengan User-Agent Custom"""
    logging.info("[STEP 0A] Fetching CoinGecko Gems (Page 1-3)...")
    gems = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        for page in range(1, 4):
            params = {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 100,
                "page": page,
                "sparkline": "false"
            }
            res = requests.get(COINGECKO_MARKETS_API, params=params, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                for coin in data:
                    sym = str(coin.get("symbol", "")).upper()
                    if sym:
                        gems.append({
                            "id": coin.get("id"),
                            "symbol": sym,
                            "cg_price": coin.get("current_price")
                        })
            else:
                logging.warning(f"[DEBUG] CoinGecko returned status code: {res.status_code}")
    except Exception as e:
        logging.error(f"Error fetching CoinGecko: {e}")
    
    logging.info(f"[DEBUG] CoinGecko gems fetched: {len(gems)}")
    return gems

def get_dia_oracle_price(symbol):
    try:
        url = f"{DIA_ORACLE_API}/{symbol.upper()}"
        res = requests.get(url, timeout=2)
        if res.status_code == 200:
            data = res.json()
            return float(data.get("Price", 0))
    except Exception:
        pass
    return None

def step1_liquidity_and_oracle_filter():
    logging.info("[STEP 1] Running Liquidity Screening ($50k-$15M) & Oracle Price Deviation Verification...")
    
    # 1. Fetch Binance Active Tickers
    try:
        res = requests.get(BINANCE_REST_24HR, timeout=8).json()
        binance_map = {t['symbol']: t for t in res if 'symbol' in t}
        logging.info(f"[DEBUG] Binance active tickers fetched: {len(binance_map)}")
    except Exception as e:
        logging.error(f"Error fetching Binance 24h Tickers: {e}")
        return []

    # 2. Fetch CoinGecko Gems (dengan User-Agent Header)
    gems = fetch_coingecko_gems()
    cg_symbols = {g['symbol']: g for g in gems}

    passed_step1 = []

    # 3. AUTO-FALLBACK LOGIC: Jika CoinGecko Kosong/Rate-Limited, Langsung Scan Seluruh Market Binance
    if not cg_symbols:
        logging.warning("[FALLBACK] CoinGecko API kosong / rate limit. Otomatis beralih memindai seluruh pair USDT di Binance...")
        for pair, t in binance_map.items():
            if pair.endswith("USDT") and not any(x in pair for x in ["UPUSDT", "DOWNUSDT", "BEAR", "BULL"]):
                vol_24h = float(t.get('quoteVolume', 0))
                cex_price = float(t.get('lastPrice', 0))
                sym = pair.replace("USDT", "")

                if 50000 <= vol_24h <= 15000000 and cex_price > 0:
                    passed_step1.append({
                        "symbol": sym,
                        "pair": pair,
                        "price": cex_price,
                        "volume_24h": vol_24h,
                        "deviation_pct": 0.0
                    })
    else:
        # Jika CoinGecko berhasil di-fetch, cocokkan dengan Binance + DIA Oracle
        for sym, gem in cg_symbols.items():
            pair = f"{sym}USDT"
            if pair in binance_map:
                t = binance_map[pair]
                vol_24h = float(t.get('quoteVolume', 0))
                cex_price = float(t.get('lastPrice', 0))

                if 50000 <= vol_24h <= 15000000 and cex_price > 0:
                    cg_price = gem.get('cg_price')
                    dia_price = get_dia_oracle_price(sym)

                    prices = [p for p in [cex_price, cg_price, dia_price] if p is not None and p > 0]
                    
                    if len(prices) >= 2:
                        min_p, max_p = min(prices), max(prices)
                        deviation = (max_p - min_p) / min_p
                        
                        if deviation < 0.03:  # Toleransi 3%
                            passed_step1.append({
                                "symbol": sym,
                                "pair": pair,
                                "price": cex_price,
                                "volume_24h": vol_24h,
                                "deviation_pct": round(deviation * 100, 3)
                            })
                    else:
                        passed_step1.append({
                            "symbol": sym,
                            "pair": pair,
                            "price": cex_price,
                            "volume_24h": vol_24h,
                            "deviation_pct": 0.0
                        })

    logging.info(f"[STEP 1 PASSED] {len(passed_step1)} coins passed Liquidity & Oracle screening.")
    return passed_step1

def calculate_rsi_fast(coins):
    logging.info(f"[STEP 2] Calculating 1H RSI (Range 30 - 68) for {len(coins)} candidate coins...")
    passed_step2 = []
    
    # Ambil maksimal 80 koin berdasar volume tertinggi untuk efisiensi runner
    sorted_coins = sorted(coins, key=lambda x: x['volume_24h'], reverse=True)[:80]
    
    for c in sorted_coins:
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={c['pair']}&interval=1h&limit=30"
            res = requests.get(url, timeout=3).json()
            if isinstance(res, list) and len(res) >= 15:
                closes = [float(k[4]) for k in res]
                df = pd.DataFrame({"close": closes})
                
                rsi_series = ta.momentum.RSIIndicator(close=df["close"], window=14).rsi()
                current_rsi = float(rsi_series.iloc[-1])

                if 30 <= current_rsi <= 68:
                    c["rsi"] = round(current_rsi, 2)
                    passed_step2.append(c)
        except Exception:
            pass

    logging.info(f"[STEP 2 PASSED] {len(passed_step2)} coins passed RSI (30-68) screening.")
    return passed_step2

def check_whale_activity_fast(symbol, pair):
    whale_score = 0
    detected_whales = []
    
    # 1. CoinLobster Check
    try:
        res_crypto = requests.get(COINLOBSTER_CRYPTO_WHALES, timeout=2)
        if res_crypto.status_code == 200:
            if symbol.lower() in res_crypto.text.lower():
                whale_score += 20
                detected_whales.append("CoinLobster On-Chain Activity")
    except Exception:
        pass

    # 2. Binance WS Quick Sampling (Timeout 1.5 detik agar anti-hang)
    try:
        trade_ws_url = f"wss://stream.binance.com:9443/ws/{pair.lower()}@trade"
        ws = websocket.create_connection(trade_ws_url, timeout=1.5)
        trades = []
        start_time = time.time()
        while time.time() - start_time < 1.0:
            msg = json.loads(ws.recv())
            p = float(msg.get('p', 0))
            q = float(msg.get('q', 0))
            trades.append(p * q)
        ws.close()

        max_trade = max(trades) if trades else 0
        if max_trade >= 3000:
            whale_score += 20
            detected_whales.append(f"Binance WS Large Trade (${max_trade:,.2f})")
    except Exception:
        pass

    if not detected_whales:
        detected_whales.append("None (Standard Flow)")

    return whale_score, detected_whales

def send_telegram_alert(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=4)
        except Exception as e:
            logging.error(f"Failed to send Telegram alert: {e}")

def run_scouting_bot():
    logging.info("========== STARTING CRYPTO SCOUTING BOT V5 PIPELINE ==========")
    
    # Step 1: Liquidity + Oracle + Auto-Fallback
    step1_coins = step1_liquidity_and_oracle_filter()
    
    # Step 2: RSI Screening
    step2_coins = calculate_rsi_fast(step1_coins)
    
    # Step 3, 4, 5, 6: Whale Check & Grading
    qualified_signals = []
    for c in step2_coins:
        whale_score, detected_whales = check_whale_activity_fast(c['symbol'], c['pair'])
        
        base_score = 40
        if 40 <= c['rsi'] <= 55:
            base_score += 20
        elif 55 < c['rsi'] <= 68:
            base_score += 15
            
        final_score = base_score + whale_score
        
        if final_score >= 60:
            c['score'] = final_score
            c['detected_whales'] = ", ".join(detected_whales)
            c['entry_price'] = c['price']
            c['stop_loss'] = round(c['price'] * 0.98, 6)
            c['take_profit'] = round(c['price'] * 1.05, 6)
            c['max_slippage'] = "0.2%"
            c['rec_risk_per_trade'] = "1% - 2% Balance"
            
            qualified_signals.append(c)

    logging.info(f"========== SCOUTING COMPLETED: FOUND {len(qualified_signals)} QUALIFIED SIGNALS ==========")
    
    for sig in qualified_signals:
        alert_msg = (
            "🎯 *SCOUTING BOT SIGNAL DETECTED* 🎯\n\n"
            f"• *Coin:* `{sig['pair']}`\n"
            f"• *Entry Price:* `${sig['entry_price']}`\n"
            f"• *Volume 24h:* `${sig['volume_24h']:,.2f}`\n"
            f"• *RSI (1H):* `{sig['rsi']}`\n"
            f"• *Grading Score:* `{sig['score']}%`\n"
            f"• *Detected Whale:* `{sig['detected_whales']}`\n\n"
            "🛡 *Position Sizing & Risk Management:*\n"
            f"• *Stop Loss (2%):* `${sig['stop_loss']}`\n"
            f"• *Take Profit (5%):* `${sig['take_profit']}`\n"
            f"• *Max Slippage:* `{sig['max_slippage']}`\n"
            f"• *Recommended Risk:* `{sig['rec_risk_per_trade']}`"
        )
        print(alert_msg)
        print("-" * 50)
        send_telegram_alert(alert_msg)

if __name__ == "__main__":
    run_scouting_bot()

import time
import json
import logging
import os
import requests
import pandas as pd
import ta
import websocket

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ==========================================
# ENDPOINT API & WEBSOCKET CONFIGURATION
# ==========================================
BINANCE_REST_PRICE = "https://api.binance.com/api/v3/ticker/price"
BINANCE_REST_24HR = "https://api.binance.com/api/v3/ticker/24hr"
COINGECKO_PRICE_API = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
COINGECKO_MARKETS_API = "https://api.coingecko.com/api/v3/coins/markets"
DIA_ORACLE_API = "https://api.diadata.org/v1/quotation"
COINLOBSTER_CRYPTO_WHALES = "https://coinlobster.com/api/public/crypto-whales"
COINLOBSTER_ONCHAIN_WHALES = "https://coinlobster.com/api/public/onchain-whales"

# ==========================================
# STEP 0 & STEP 1: DUAL-LAYER FILTER & PARALLEL DATA CHECK
# ==========================================
def fetch_coingecko_gems():
    """[STEP 0A] Fetch daftar koin gems (Halaman 1-3) + Harga global"""
    logging.info("[STEP 0A] Fetching CoinGecko Gems (Page 1-3)...")
    gems = []
    try:
        for page in range(1, 4):
            params = {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 100,
                "page": page,
                "sparkline": "false"
            }
            res = requests.get(COINGECKO_MARKETS_API, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                for coin in data:
                    gems.append({
                        "id": coin.get("id"),
                        "symbol": coin.get("symbol", "").upper(),
                        "cg_price": coin.get("current_price")
                    })
    except Exception as e:
        logging.error(f"Error fetching CoinGecko: {e}")
    return gems

def get_dia_oracle_price(symbol):
    """[STEP 0A] DIA Data API: Verifikasi harga oracle terdesentralisasi"""
    try:
        url = f"{DIA_ORACLE_API}/{symbol.upper()}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            return float(data.get("Price", 0))
    except Exception:
        pass
    return None

def step1_liquidity_and_oracle_filter(gems):
    """
    [STEP 1] DUAL-LAYER FILTER LIKUIDITAS & PARALEL DATA CHECK
    - Is Volume 24h >= $100,000 AND <= $5,000,000?
    - Price Deviation (CoinGecko vs DIA vs CEX) < 1%?
    """
    logging.info("[STEP 1] Running Liquidity Screening & Oracle Price Deviation Verification...")
    
    try:
        res = requests.get(BINANCE_REST_24HR, timeout=10).json()
        binance_map = {t['symbol']: t for t in res if 'symbol' in t}
    except Exception as e:
        logging.error(f"Error fetching Binance 24h Tickers: {e}")
        return []

    passed_step1 = []
    for gem in gems:
        pair = f"{gem['symbol']}USDT"
        if pair in binance_map:
            t = binance_map[pair]
            vol_24h = float(t.get('quoteVolume', 0))
            cex_price = float(t.get('lastPrice', 0))

            if 100000 <= vol_24h <= 5000000 and cex_price > 0:
                cg_price = gem.get('cg_price')
                dia_price = get_dia_oracle_price(gem['symbol'])

                prices = [p for p in [cex_price, cg_price, dia_price] if p is not None and p > 0]
                
                if len(prices) >= 2:
                    min_p, max_p = min(prices), max(prices)
                    deviation = (max_p - min_p) / min_p
                    
                    if deviation < 0.01:
                        passed_step1.append({
                            "symbol": gem['symbol'],
                            "pair": pair,
                            "price": cex_price,
                            "volume_24h": vol_24h,
                            "deviation_pct": round(deviation * 100, 3)
                        })

    logging.info(f"[STEP 1 PASSED] {len(passed_step1)} coins passed Liquidity & Oracle screening.")
    return passed_step1

# ==========================================
# STEP 2: RSI INDICATOR FILTER (30 - 60)
# ==========================================
def step2_rsi_filter(coins):
    """[STEP 2] Filter Indikator RSI (30-60)"""
    logging.info("[STEP 2] Screening RSI (30 - 60)...")
    passed_step2 = []
    
    for c in coins:
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={c['pair']}&interval=1h&limit=50"
            res = requests.get(url, timeout=5).json()
            closes = [float(k[4]) for k in res]
            df = pd.DataFrame({"close": closes})
            
            rsi_series = ta.momentum.RSIIndicator(close=df["close"], window=14).rsi()
            current_rsi = float(rsi_series.iloc[-1])

            if 30 <= current_rsi <= 60:
                c["rsi"] = round(current_rsi, 2)
                passed_step2.append(c)
        except Exception:
            pass

    logging.info(f"[STEP 2 PASSED] {len(passed_step2)} coins passed RSI screening.")
    return passed_step2

# ==========================================
# STEP 3: REAL-TIME WHALE & ORDERBOOK MONITORING
# ==========================================
def step3_whale_detection(symbol, pair):
    """[STEP 3] Deteksi Masuknya Whale"""
    whale_score = 0
    
    try:
        res_crypto = requests.get(COINLOBSTER_CRYPTO_WHALES, timeout=4)
        if res_crypto.status_code == 200:
            data = res_crypto.text.lower()
            if symbol.lower() in data:
                whale_score += 20
    except Exception:
        pass

    try:
        trade_ws_url = f"wss://stream.binance.com:9443/ws/{pair.lower()}@trade"
        ws = websocket.create_connection(trade_ws_url, timeout=3)
        trades = []
        start_time = time.time()
        while time.time() - start_time < 2:
            msg = json.loads(ws.recv())
            price = float(msg.get('p', 0))
            qty = float(msg.get('q', 0))
            trades.append(price * qty)
        ws.close()

        if any(t_vol >= 5000 for t_vol in trades):
            whale_score += 20
    except Exception:
        pass

    return whale_score

# ==========================================
# STEP 4, 5, 6: GRADING, POSITION SIZING & EXECUTION
# ==========================================
def send_telegram_alert(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logging.error(f"Failed to send Telegram alert: {e}")

def run_scouting_bot():
    logging.info("========== STARTING CRYPTO SCOUTING BOT PIPELINE ==========")
    
    gems = fetch_coingecko_gems()
    step1_coins = step1_liquidity_and_oracle_filter(gems)
    step2_coins = step2_rsi_filter(step1_coins)
    
    qualified_signals = []
    for c in step2_coins:
        whale_score = step3_whale_detection(c['symbol'], c['pair'])
        
        base_score = 50
        if 40 <= c['rsi'] <= 50:
            base_score += 20
            
        final_score = base_score + whale_score
        
        if final_score >= 60:
            c['score'] = final_score
            c['entry_price'] = c['price']
            c['stop_loss'] = round(c['price'] * 0.98, 6)
            c['take_profit'] = round(c['price'] * 1.05, 6)
            c['max_slippage'] = "0.2%"
            c['rec_risk_per_trade'] = "1% - 2% Account Balance"
            
            qualified_signals.append(c)

    logging.info(f"========== SCOUTING COMPLETED: FOUND {len(qualified_signals)} QUALIFIED SIGNALS ==========")
    
    for sig in qualified_signals:
        pair_str = sig['pair']
        entry_str = sig['entry_price']
        vol_str = f"{sig['volume_24h']:,.2f}"
        rsi_str = sig['rsi']
        score_str = sig['score']
        dev_str = sig['deviation_pct']
        sl_str = sig['stop_loss']
        tp_str = sig['take_profit']
        slip_str = sig['max_slippage']
        risk_str = sig['rec_risk_per_trade']

        alert_msg = (
            "🎯 *SCOUTING BOT SIGNAL DETECTED* 🎯\n\n"
            f"• *Coin:* `{pair_str}`\n"
            f"• *Entry Price:* `${entry_str}`\n"
            f"• *Volume 24h:* `${vol_str}`\n"
            f"• *RSI (1H):* `{rsi_str}`\n"
            f"• *Grading Score:* `{score_str}%`\n"
            f"• *Price Dev:* `{dev_str}%`\n\n"
            "🛡 *Position Sizing & Risk Management:*\n"
            f"• *Stop Loss (2%):* `${sl_str}`\n"
            f"• *Take Profit (5%):* `${tp_str}`\n"
            f"• *Max Slippage:* `{slip_str}`\n"
            f"• *Recommended Risk:* `{risk_str}`"
        )
        print(alert_msg)
        print("-" * 50)
        send_telegram_alert(alert_msg)

if __name__ == "__main__":
    run_scouting_bot()

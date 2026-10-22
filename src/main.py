import os
import logging
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ==========================================
# KONFIGURASI BOT (OPTIMAL & BEBAS RATE LIMIT)
# ==========================================
DATA_SOURCE = "AUTO"          # "AUTO", "BINANCE", "BYBIT"
MIN_TURNOVER_24H = 50000      # Minimal Volume $50.000
PASSING_SCORE = 50            # Threshold Lolos Sinyal (50%)

BINANCE_REST_24HR = "https://api.binance.com/api/v3/ticker/24hr"
BYBIT_REST_24HR = "https://api.bybit.com/v5/market/tickers"

def fetch_market_data():
    """Mengambil seluruh data pasar aktif tanpa pemicu rate limit"""
    logging.info(f"[STEP 1] Fetching Market Data (Min Turnover: ${MIN_TURNOVER_24H:,.0f})...")
    market_map = {}

    # 1. Fetch Binance
    if DATA_SOURCE in ["BINANCE", "AUTO"]:
        try:
            res = requests.get(BINANCE_REST_24HR, timeout=8).json()
            if isinstance(res, list):
                for t in res:
                    pair = t.get('symbol', '')
                    if pair.endswith("USDT") and not any(x in pair for x in ["UPUSDT", "DOWNUSDT", "BEAR", "BULL"]):
                        vol_24h = float(t.get('quoteVolume', 0))
                        price = float(t.get('lastPrice', 0))
                        change_pct = float(t.get('priceChangePercent', 0))
                        
                        if vol_24h >= MIN_TURNOVER_24H and price > 0:
                            sym = pair.replace("USDT", "")
                            market_map[sym] = {
                                "symbol": sym,
                                "pair": pair,
                                "price": price,
                                "volume_24h": vol_24h,
                                "change_pct": change_pct,
                                "source": "Binance"
                            }
        except Exception as e:
            logging.error(f"Error fetching Binance: {e}")

    # 2. Fetch Bybit (Fallback)
    if DATA_SOURCE in ["BYBIT", "AUTO"] and (not market_map or DATA_SOURCE == "BYBIT"):
        try:
            res = requests.get(f"{BYBIT_REST_24HR}?category=spot", timeout=8).json()
            if res.get("retCode") == 0:
                for t in res.get("result", {}).get("list", []):
                    pair = t.get('symbol', '')
                    if pair.endswith("USDT"):
                        vol_24h = float(t.get('turnover24h', 0))
                        price = float(t.get('lastPrice', 0))
                        change_pct = float(t.get('price24hPcnt', 0)) * 100
                        sym = pair.replace("USDT", "")
                        
                        if vol_24h >= MIN_TURNOVER_24H and price > 0 and sym not in market_map:
                            market_map[sym] = {
                                "symbol": sym,
                                "pair": pair,
                                "price": price,
                                "volume_24h": vol_24h,
                                "change_pct": change_pct,
                                "source": "Bybit"
                            }
        except Exception as e:
            logging.error(f"Error fetching Bybit: {e}")

    logging.info(f"[STEP 1 PASSED] Found {len(market_map)} active pairs matching liquidity criteria.")
    return list(market_map.values())

def analyze_and_grade(coins):
    """Sistem Evaluasi dan Grading Cepat"""
    logging.info(f"[STEP 2] Analyzing and Grading {len(coins)} candidates...")
    qualified = []

    for c in coins:
        score = 50  # Base score lolos filter likuiditas
        whale_notes = []

        # 1. Evaluasi Volume Turnover
        if c['volume_24h'] >= 2000000:
            score += 25
            whale_notes.append(f"High Volume (${c['volume_24h']:,.0f})")
        elif c['volume_24h'] >= 300000:
            score += 15
            whale_notes.append("Moderate Capital Flow")

        # 2. Evaluasi Price Momentum
        if c['change_pct'] >= 3.0:
            score += 25
            whale_notes.append(f"Bullish Momentum (+{c['change_pct']:.2f}%)")
        elif c['change_pct'] > 0:
            score += 10
            whale_notes.append(f"Positive Trend (+{c['change_pct']:.2f}%)")

        if not whale_notes:
            whale_notes.append("Standard Flow")

        if score >= PASSING_SCORE:
            c['score'] = score
            c['whale_info'] = ", ".join(whale_notes)
            c['stop_loss'] = round(c['price'] * 0.98, 6)
            c['take_profit'] = round(c['price'] * 1.05, 6)
            qualified.append(c)

    logging.info(f"[STEP 2 PASSED] {len(qualified)} coins qualified for signal alert.")
    return qualified

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
    logging.info("========== STARTING CRYPTO SCOUTING BOT ==========")
    
    # Step 1 & 2: Fetch & Grade
    candidates = fetch_market_data()
    qualified_signals = analyze_and_grade(candidates)

    logging.info(f"========== SCOUTING COMPLETED: FOUND {len(qualified_signals)} QUALIFIED SIGNALS ==========")
    
    # Tampilkan maksimal 10 sinyal teratas berdasar skor/volume
    top_signals = sorted(qualified_signals, key=lambda x: (x['score'], x['volume_24h']), reverse=True)[:10]

    for sig in top_signals:
        alert_msg = (
            "🎯 *SCOUTING BOT SIGNAL DETECTED* 🎯\n\n"
            f"• *Coin:* `{sig['pair']}` ({sig['source']})\n"
            f"• *Entry Price:* `${sig['price']}`\n"
            f"• *Volume 24h:* `${sig['volume_24h']:,.2f}`\n"
            f"• *Price Change (24h):* `{sig['change_pct']:.2f}%`\n"
            f"• *Grading Score:* `{sig['score']}%`\n"
            f"• *Whale Status:* `{sig['whale_info']}`\n\n"
            "🛡 *Risk Management:*\n"
            f"• *Stop Loss (2%):* `${sig['stop_loss']}`\n"
            f"• *Take Profit (5%):* `${sig['take_profit']}`"
        )
        print(alert_msg)
        print("-" * 50)
        send_telegram_alert(alert_msg)

if __name__ == "__main__":
    run_scouting_bot()

# Crypto Scouting Bot (GitHub Actions Free-Tier) - Fixed

Bot scouting otomatis yang berjalan via GitHub Actions (Cron) untuk memindai koin potensial (Gems) berdasarkan alur filter multi-layer:
1. **Step 0 & 1:** Liquidity Screening (Vol $100k-$5M) & Price Verification (CoinGecko, DIA, Binance CEX).
2. **Step 2:** RSI Screening (Range 30 - 60).
3. **Step 3:** Whale Flow Detection (CoinLobster & Live Binance WS @trade/@depth5).
4. **Step 4:** System Grading (60% - 100%).
5. **Step 5:** Position Sizing & Slippage Guard.
6. **Step 6:** Telegram Alert Signal Output.

## Cara Setup di GitHub Free-Tier:

1. **Push Repository ke GitHub:**
   ```bash
   git init
   git add .
   git commit -m "Fix syntax error multiline string"
   git branch -M main
   git remote add origin https://github.com/USERNAME/REPO_NAME.git
   git push -u origin main
   ```

2. **Setup Repository Secrets (Opsional untuk Telegram Alert):**
   Buka Repository GitHub -> **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**:
   - `TELEGRAM_BOT_TOKEN`: Token dari `@BotFather`
   - `TELEGRAM_CHAT_ID`: Chat ID Telegram Anda

3. **Jalankan Bot:**
   - Bot otomatis berjalan via Cron setiap 15 menit.
   - Anda juga bisa trigger manual di menu **Actions** -> **Crypto Scouting Bot Cron** -> **Run workflow**.

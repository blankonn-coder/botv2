# Crypto Scouting Bot V2 (GitHub Actions Free-Tier)

Bot scouting otomatis yang berjalan via GitHub Actions (Cron) untuk memindai koin potensial (Gems) berdasarkan alur filter multi-layer yang telah disesuaikan:
1. **Step 0 & 1:** Liquidity Screening (Vol $50k-$15M) & Price Verification (Toleransi 3% + Fallback Oracle).
2. **Step 2:** RSI Screening (Range 30 - 68).
3. **Step 3:** Whale Flow Detection (CoinLobster & Live Binance WS @trade/@depth5) + Deteksi Spesifik Whale.
4. **Step 4:** New Scoring System (Passing Grade 60%).
5. **Step 5:** Position Sizing & Slippage Guard.
6. **Step 6:** Telegram Alert Signal Output (Lengkap dengan info Detected Whale).

## Cara Setup di GitHub Free-Tier:

1. **Push Repository ke GitHub:**
   ```bash
   git init
   git add .
   git commit -m "Update scouting bot v2 with relaxed filters & detected whale info"
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

# NSE Banker RSI Dashboard

A local dashboard for NSE EQ-series stocks that surfaces **Banker RSI** buy signals based on the MCDX indicator (LOKEN BULLISH MCDX v2.2).

Three signal tiers:
- 🟢 **5-day setup** — `banker_rsi` was 0 for the prior 5 days, then crosses above 0 today
- 🔵 **3-day setup** — same but 3-day silence period
- 🟡 **Immediate** — `banker_rsi > 0` today (any cross)
- ▲ **Bull** — `banker_rsi > 8.5` (strong confirmation)

Also generates TradingView watchlist strings for each signal tier.

---

## Architecture

```
data/               ← NSE daily CSV files dropped here
backend/
  nse_to_mysql_with_banker_signal.py   ← loader: CSV → MySQL
  nse_watcher.py                       ← file watcher (auto-loads new CSVs)
  nse_api.py                           ← Flask REST API
frontend/
  src/NseApp.jsx                       ← React dashboard UI
```

---

## Prerequisites

- Python 3.10+
- MySQL 8.x (running locally or on a server)
- Node.js 18+ / npm

---

## Backend setup

```bash
cd backend

# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Configure credentials
cp .env.example .env
# Edit .env — set DB_HOST, DB_USER, DB_PASSWORD, EOD_FOLDER

# 3. Load historical data (run once, or whenever you have a batch of CSVs)
python nse_to_mysql_with_banker_signal.py

# 4. Start the API server
python nse_api.py
# API runs on http://localhost:5001

# 5. (Optional) Auto-load new CSVs as they arrive
python nse_watcher.py
```

### `.env` reference

| Variable | Default | Description |
|---|---|---|
| `DB_HOST` | `localhost` | MySQL host |
| `DB_PORT` | `3306` | MySQL port |
| `DB_NAME` | `nse_eod` | Database name (auto-created) |
| `DB_USER` | `root` | MySQL username |
| `DB_PASSWORD` | *(empty)* | MySQL password |
| `EOD_FOLDER` | `./bhavcopy` | Folder with `*_NSE.csv` files |
| `SERIES_FILTER` | `EQ` | Series to load (`EQ`, or leave blank for all) |
| `FLASK_PORT` | `5001` | Port for the API server |

---

## Frontend setup

```bash
cd frontend

# 1. Install dependencies
npm install

# 2. Configure API URL (optional — defaults to localhost:5001)
cp .env.example .env
# Edit VITE_API_URL if your API runs on a different host/port

# 3. Start dev server
npm run dev
# Dashboard at http://localhost:3001

# 4. Production build
npm run build
```

---

## NSE CSV format

The loader expects NSE Bhavcopy files named:
- `YYYYMMDD_NSE.csv` (e.g. `20240523_NSE.csv`)
- `NSE_YYYYMMDD.csv`

Required columns: `SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN`

---

## API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/health` | DB connection check + row count |
| `GET /api/dates` | Last 60 available trade dates |
| `GET /api/signal-day?date=YYYY-MM-DD` | Signals for a specific date |
| `GET /api/signals?days=7` | Signals for the last N trading days |

---

## Development notes

- The dashboard auto-refreshes the date list every 60 seconds — useful when running alongside the watcher.
- The loader uses `ON DUPLICATE KEY UPDATE`, so re-running it on the same files is safe.
- Tickers with fewer than 50 rows of history will have `NULL` for all signal columns (RSI period = 50).

---

## License

MIT

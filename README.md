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
data/               ← NSE daily CSV files dropped here (gitignored)
backend/
  nse_to_mysql_with_banker_signal.py   ← loader: CSV → MySQL (with RSI warm-up)
  nse_watcher.py                       ← file watcher (auto-loads new CSVs)
  nse_api.py                           ← Flask REST API
  downloader.py                        ← auto-downloads daily bhavcopy CSVs
  requirements.txt
  .env.example                         ← copy to .env and fill in your details
frontend/
  src/NseApp.jsx                       ← React dashboard UI
  src/main.jsx
  index.html
  package.json
  vite.config.js
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

# 1. Create and activate a virtual environment (recommended)
python3 -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Configure credentials
cp .env.example .env
# Edit .env — set DB_HOST, DB_USER, DB_PASSWORD, EOD_FOLDER

# 4. Load historical data (run once with all your CSVs in EOD_FOLDER)
python nse_to_mysql_with_banker_signal.py

# 5. Start the API server
python nse_api.py
# API runs on http://localhost:5001

# 6. (Optional) Auto-load new CSVs as they arrive
python nse_watcher.py

# 7. (Optional) Auto-download today's bhavcopy
python downloader.py
```

### `.env` reference

| Variable | Default | Description |
|---|---|---|
| `DB_HOST` | `localhost` | MySQL host |
| `DB_PORT` | `3306` | MySQL port |
| `DB_NAME` | `nse_eod` | Database name (auto-created) |
| `DB_USER` | `root` | MySQL username |
| `DB_PASSWORD` | *(empty)* | MySQL password |
| `EOD_FOLDER` | `./data` | Folder where bhavcopy CSVs are placed |
| `LOADER_SCRIPT` | `./nse_to_mysql_with_banker_signal.py` | Path to loader (used by watcher) |
| `PYTHON_PATH` | `python3` | Python executable (used by watcher) |
| `FLASK_PORT` | `5001` | Port for the API server |

---

## Frontend setup

```bash
cd frontend

# 1. Install dependencies
npm install

# 2. Start dev server
npm run dev
# Dashboard at http://localhost:3001

# 3. Production build
npm run build
```

---

## Data

Download NSE bhavcopy CSVs from [nseindia.com](https://www.nseindia.com/all-reports) or [samco.in/bhavcopy](https://www.samco.in/bhavcopy-nse-bse-mcx) and place them in the folder set as `EOD_FOLDER` in your `backend/.env`.

The loader expects NSE Bhavcopy files named:
- `YYYYMMDD_NSE.csv` (e.g. `20240523_NSE.csv`)
- `NSE_YYYYMMDD.csv`

Required columns: `SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN`

### How the loader handles daily updates

When a new CSV is detected, the loader:
1. Fetches the last 100 rows per ticker from the DB as RSI warm-up history
2. Prepends that history to the new file's rows
3. Computes the full RSI + Banker signal chain over the combined series
4. Upserts only the new date's rows into MySQL

This ensures `banker_rsi` is always correctly computed regardless of how many new files are loaded at once. Tickers with fewer than 50 rows of total history will have `NULL` signal columns until enough data accumulates.

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
- If you need to recompute signals for already-loaded dates (e.g. after a fix), temporarily set `loaded_dates = set()` in the loader's `__main__` block, run it, then restore.
- The `.env` file is gitignored — never committed. Copy `.env.example` to `.env` and fill in your own credentials.

---

## License

MIT

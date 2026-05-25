# Changelog

All notable changes to this project will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/).

---

## [1.2.0] — 2026-05-25

### Fixed
- **Critical: banker_rsi was NULL for all tickers on every date.** The loader previously computed RSI only from the rows in the new file (1 row per ticker), which is not enough to seed the 50-period Wilder RSI. All signal columns were silently stored as NULL, producing no signals in the dashboard.
- **Critical: dashboard did not load tickers.** The API query fetched every historical row for every ticker and filtered to 7 rows per ticker in Python — potentially millions of rows. Replaced with a SQL `ROW_NUMBER()` window function that returns at most 7 rows per ticker directly from MySQL.
- `decimal.Decimal` TypeError in RSI computation when history rows fetched from MySQL were passed to `series.diff()`. Fixed by casting close prices to `float` before RSI computation.

### Added
- `fetch_history_for_tickers()` in loader: pulls the last 100 rows per ticker from the DB before the new file's date, prepends them as RSI warm-up history, then discards them after computation — only new date rows are upserted.
- NSE bhavcopy downloader script: auto-downloads daily bhavcopy CSVs, watcher detects new file and triggers loader automatically.
- `FLASK_PORT` now read from `.env` (default `5001`).

### Changed
- `add_banker_signals()` now accepts a `new_dates` set — computes signals over the full history+new series but only returns new date rows for upsert.
- API `compute_signals_for_date()` now uses `ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY trade_date DESC)` to fetch only 7 rows per ticker efficiently.

---

## [1.1.0] — 2026-05-15

### Added
- Flask REST API (`nse_api.py`) with `/api/dates`, `/api/signal-day`, `/api/signals`, `/api/health` endpoints
- NSE bhavcopy CSV loader (`nse_to_mysql_with_banker_signal.py`) with full MCDX Banker RSI computation
- File watcher (`nse_watcher.py`) to auto-load new bhavcopy CSVs on arrival
- React dashboard (`NseApp.jsx`) with signal table, filter bar, summary cards, and TradingView watchlist export
- Three signal tiers: 5-day setup, 3-day setup, immediate RSI > 0
- Bull flag (banker_rsi > 8.5) overlay
- Dark mode support via CSS variables
- Sortable table columns (ticker, signal strength, RSI, close price)
- Ticker search filter
- Expandable rows showing prior-day RSI chips and banker MA/signal values
- Auto-refresh of date list every 60 seconds
- Environment-variable based configuration (no hardcoded credentials)

---

## [1.0.0] — 2025-05-15

### Added
- Initial release

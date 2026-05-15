# Changelog

All notable changes to this project will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/).

---

## [1.0.0] — 2025-05-15

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

"""
NSE EOD → MySQL Loader with Banker Signal
==========================================
Reads all NSE daily CSV files (e.g. 20240523_NSE.csv) from a folder,
computes the MCDX Banker RSI signal (from LOKEN BULLISH MCDX v2.2),
and inserts everything into a MySQL database.

Expected CSV columns (NSE Bhavcopy format):
  SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST,
  PREVCLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN

Columns stored per row (in addition to OHLCV):
  delta, u (gain), d (loss), avg_gain, avg_loss, rs, rsi,
  raw_banker (before clamping), banker_rsi (clamped 0-20),
  banker_ma, banker_signal, banker_bull

Requirements:
    pip install pandas mysql-connector-python numpy python-dotenv

Usage:
    1. Copy backend/.env.example → backend/.env and fill in your values.
    2. Run: python nse_to_mysql_with_banker_signal.py
"""

import os
import glob
import numpy as np
import pandas as pd
import mysql.connector
from mysql.connector import Error

# Load .env if present (ignored in production where env vars are set directly)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional; set env vars manually if not installed

# ─────────────────────────────────────────────
# CONFIGURATION — read from environment
# ─────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "3306")),
    "database": os.getenv("DB_NAME",     "nse_eod"),
    "user":     os.getenv("DB_USER",     "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "use_pure": True,
}

EOD_FOLDER = os.getenv("EOD_FOLDER", "./bhavcopy")

# Set to a comma-separated string like "EQ" to load only equity series,
# or leave blank / unset to load all series.
_series_env = os.getenv("SERIES_FILTER", "EQ").strip()
SERIES_FILTER = [s.strip() for s in _series_env.split(",") if s.strip()] if _series_env else None

# ─────────────────────────────────────────────
# MCDX BANKER SIGNAL PARAMETERS (match Pine)
# ─────────────────────────────────────────────
RSI_BASE_BANKER    = 50
RSI_PERIOD_BANKER  = 50
SENSITIVITY_BANKER = 1.5


# ─────────────────────────────────────────────
# RSI — returns all intermediate columns
# ─────────────────────────────────────────────
def compute_rsi_full(series: pd.Series, period: int) -> pd.DataFrame:
    if len(series) <= period:
        nan = pd.Series(np.nan, index=series.index)
        return pd.DataFrame({
            "delta": series.diff(), "u": nan, "d": nan,
            "avg_gain": nan, "avg_loss": nan, "rs": nan, "rsi": nan,
        })

    delta = series.diff()
    u = delta.clip(lower=0)
    d = (-delta).clip(lower=0)

    avg_gain = np.full(len(series), np.nan)
    avg_loss = np.full(len(series), np.nan)

    # First value: simple average over first `period` bars (Pine's seed)
    avg_gain[period] = u.iloc[1:period + 1].mean()
    avg_loss[period] = d.iloc[1:period + 1].mean()

    # Subsequent values: Wilder smoothing
    for i in range(period + 1, len(series)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + u.iloc[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + d.iloc[i]) / period

    avg_gain = pd.Series(avg_gain, index=series.index)
    avg_loss = pd.Series(avg_loss, index=series.index)

    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    return pd.DataFrame({
        "delta":    delta,
        "u":        u,
        "d":        d,
        "avg_gain": avg_gain,
        "avg_loss": avg_loss,
        "rs":       rs,
        "rsi":      rsi,
    })


# ─────────────────────────────────────────────
# BANKER RSI  (matches Pine rsi_function())
# ─────────────────────────────────────────────
def compute_banker_columns(close: pd.Series) -> pd.DataFrame:
    rsi_df = compute_rsi_full(close, RSI_PERIOD_BANKER)
    raw    = SENSITIVITY_BANKER * (rsi_df["rsi"] - RSI_BASE_BANKER)
    rsi_df["raw_banker"] = raw
    rsi_df["banker_rsi"] = raw.clip(lower=0, upper=20)
    return rsi_df


# ─────────────────────────────────────────────
# EMA / RMA / SMA helpers
# ─────────────────────────────────────────────
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, min_periods=period, adjust=False).mean()

def rma(series: pd.Series, period: int) -> pd.Series:
    """Pine rma = Wilder MA = EWM with alpha 1/period."""
    return series.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


# ─────────────────────────────────────────────
# BANKER MA / SIGNAL  (matches Pine bankma / banksignal)
# ─────────────────────────────────────────────
def compute_banker_ma_signal(rsi_banker: pd.Series):
    """
    bankma2    = sma(rsi_Banker, 2)
    bankma7    = ema(rsi_Banker, 7)
    bankma31   = ema(rsi_Banker, 31)
    bankma     = sma((bankma2*70 + bankma7*20 + bankma31*10)/100, 1)
    banksignal = rma(bankma, 4)
    """
    bankma2    = sma(rsi_banker, 2)
    bankma7    = ema(rsi_banker, 7)
    bankma31   = ema(rsi_banker, 31)
    bankma     = sma((bankma2 * 70 + bankma7 * 20 + bankma31 * 10) / 100, 1)
    banksignal = rma(bankma, 4)
    return bankma, banksignal


# ─────────────────────────────────────────────
# PARSE ONE NSE DAILY CSV FILE
# ─────────────────────────────────────────────
def parse_nse_file(filepath: str) -> pd.DataFrame:
    """
    Parses a single NSE bhavcopy CSV file.
    Filename format: YYYYMMDD_NSE.csv  (date is read from TIMESTAMP column).
    """
    df = pd.read_csv(filepath, dtype={"SYMBOL": str, "SERIES": str, "ISIN": str})

    # Normalise column names: strip spaces
    df.columns = df.columns.str.strip()

    # Rename to internal names
    df.rename(columns={
        "SYMBOL":      "ticker",
        "SERIES":      "series",
        "OPEN":        "open",
        "HIGH":        "high",
        "LOW":         "low",
        "CLOSE":       "close",
        "LAST":        "last",
        "PREVCLOSE":   "prev_close",
        "TOTTRDQTY":   "volume",
        "TOTTRDVAL":   "trd_val",
        "TIMESTAMP":   "date",
        "TOTALTRADES": "trades",
        "ISIN":        "isin",
    }, inplace=True)

    # Parse date — handles string formats ("23-MAY-2024", "27-Jun-24")
    # and Excel serial numbers (e.g. 45470 stored as integer/float in CSV)
    def parse_date_col(val):
        try:
            v = str(val).strip()
            # Excel serial number: purely numeric, no letters
            if v.replace(".", "", 1).isdigit():
                return pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(float(v)))
            return pd.to_datetime(v, dayfirst=True)
        except Exception:
            return pd.NaT

    df["date"] = df["date"].apply(parse_date_col)

    # Cast numerics
    for col in ["open", "high", "low", "close", "last", "prev_close", "trd_val"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["volume", "trades"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(np.int64)

    # Optional: filter by series
    if SERIES_FILTER:
        df = df[df["series"].isin(SERIES_FILTER)].copy()

    return df


# ─────────────────────────────────────────────
# LOAD ALL FILES → combined DataFrame
# ─────────────────────────────────────────────
def load_all_files(folder: str) -> pd.DataFrame:
    # Support both YYYYMMDD_NSE.csv and NSE_YYYYMMDD.csv naming conventions
    patterns = [
        os.path.join(folder, "*_NSE.csv"),
        os.path.join(folder, "NSE_*.csv"),
    ]
    files = []
    for pattern in patterns:
        files.extend(glob.glob(pattern))
    files = sorted(set(files))

    if not files:
        raise FileNotFoundError(
            f"No NSE CSV files found in: {folder}\n"
            "Expected filenames like 20240523_NSE.csv or NSE_20240523.csv"
        )

    print(f"Found {len(files)} NSE file(s).")
    frames = [parse_nse_file(f) for f in files]
    combined = pd.concat(frames, ignore_index=True)
    combined.sort_values(["ticker", "date"], inplace=True)
    combined.reset_index(drop=True, inplace=True)

    print(
        f"Total rows: {len(combined):,}  |  "
        f"Unique tickers: {combined['ticker'].nunique():,}  |  "
        f"Date range: {combined['date'].min().date()} → {combined['date'].max().date()}"
    )
    return combined


# ─────────────────────────────────────────────
# COMPUTE SIGNALS PER TICKER
# ─────────────────────────────────────────────
def add_banker_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Group by ticker, compute all intermediate + final Banker columns,
    then merge back.
    Tickers with < RSI_PERIOD_BANKER rows will have NaN for signal columns.
    """
    results = []
    for ticker, grp in df.groupby("ticker", sort=False):
        grp = grp.copy()

        # All intermediate RSI columns + raw_banker + banker_rsi
        cols = compute_banker_columns(grp["close"])
        grp["delta"]      = cols["delta"]
        grp["u"]          = cols["u"]
        grp["d"]          = cols["d"]
        grp["avg_gain"]   = cols["avg_gain"]
        grp["avg_loss"]   = cols["avg_loss"]
        grp["rs"]         = cols["rs"]
        grp["rsi"]        = cols["rsi"]
        grp["raw_banker"] = cols["raw_banker"]
        grp["banker_rsi"] = cols["banker_rsi"]

        # MA + signal derived from clamped banker_rsi
        grp["banker_ma"], grp["banker_signal"] = compute_banker_ma_signal(grp["banker_rsi"])

        # Bull flag: banker_rsi above 8.5 threshold (Pine bullish confirmation line)
        grp["banker_bull"] = (grp["banker_rsi"] > 8.5).astype(int)

        results.append(grp)

    enriched = pd.concat(results, ignore_index=True)
    enriched.sort_values(["ticker", "date"], inplace=True)

    # Round to 4 decimal places for all computed float columns
    float_cols = [
        "delta", "u", "d", "avg_gain", "avg_loss", "rs", "rsi",
        "raw_banker", "banker_rsi", "banker_ma", "banker_signal",
    ]
    for col in float_cols:
        enriched[col] = enriched[col].round(4)

    return enriched


# ─────────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────────
CREATE_DB_SQL = (
    "CREATE DATABASE IF NOT EXISTS {db} "
    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS nse_eod (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    ticker         VARCHAR(30)    NOT NULL,
    series         VARCHAR(10),
    trade_date     DATE           NOT NULL,
    open           DECIMAL(18,4)  NOT NULL,
    high           DECIMAL(18,4)  NOT NULL,
    low            DECIMAL(18,4)  NOT NULL,
    close          DECIMAL(18,4)  NOT NULL,
    last           DECIMAL(18,4),
    prev_close     DECIMAL(18,4),
    volume         BIGINT         NOT NULL,
    trd_val        DECIMAL(20,2),
    trades         BIGINT,
    isin           VARCHAR(20),

    -- RSI intermediate columns
    delta          DECIMAL(18,4),
    u              DECIMAL(18,4),
    d              DECIMAL(18,4),
    avg_gain       DECIMAL(10,4),
    avg_loss       DECIMAL(10,4),
    rs             DECIMAL(10,4),
    rsi            DECIMAL(10,4),

    -- Banker signal columns
    raw_banker     DECIMAL(10,4),
    banker_rsi     DECIMAL(10,4),
    banker_ma      DECIMAL(10,4),
    banker_signal  DECIMAL(10,4),
    banker_bull    TINYINT(1),

    UNIQUE KEY uq_ticker_series_date (ticker, series, trade_date),
    INDEX idx_ticker      (ticker),
    INDEX idx_date        (trade_date),
    INDEX idx_series      (series),
    INDEX idx_banker_rsi  (banker_rsi)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

INSERT_SQL = """
INSERT INTO nse_eod
    (ticker, series, trade_date, open, high, low, close, last, prev_close,
     volume, trd_val, trades, isin,
     delta, u, d, avg_gain, avg_loss, rs, rsi,
     raw_banker, banker_rsi, banker_ma, banker_signal, banker_bull)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    open          = VALUES(open),
    high          = VALUES(high),
    low           = VALUES(low),
    close         = VALUES(close),
    last          = VALUES(last),
    prev_close    = VALUES(prev_close),
    volume        = VALUES(volume),
    trd_val       = VALUES(trd_val),
    trades        = VALUES(trades),
    isin          = VALUES(isin),
    delta         = VALUES(delta),
    u             = VALUES(u),
    d             = VALUES(d),
    avg_gain      = VALUES(avg_gain),
    avg_loss      = VALUES(avg_loss),
    rs            = VALUES(rs),
    rsi           = VALUES(rsi),
    raw_banker    = VALUES(raw_banker),
    banker_rsi    = VALUES(banker_rsi),
    banker_ma     = VALUES(banker_ma),
    banker_signal = VALUES(banker_signal),
    banker_bull   = VALUES(banker_bull);
"""


def _nan_or(val):
    """Return None if NaN/inf, else a Python float."""
    if val is None:
        return None
    try:
        if pd.isna(val) or not np.isfinite(val):
            return None
    except (TypeError, ValueError):
        pass
    return float(val)


def get_connection(with_db=True):
    cfg = {k: v for k, v in DB_CONFIG.items() if k != "database"}
    cfg["auth_plugin"] = "mysql_native_password"
    if with_db:
        cfg["database"] = DB_CONFIG["database"]
    return mysql.connector.connect(**cfg)


def setup_database():
    # Create DB if needed
    conn = get_connection(with_db=False)
    cur  = conn.cursor()
    cur.execute(CREATE_DB_SQL.format(db=DB_CONFIG["database"]))
    conn.commit()
    cur.close()
    conn.close()

    # Create table
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    cur.close()
    conn.close()
    print(f"Database `{DB_CONFIG['database']}` and table `nse_eod` ready.")


# ─────────────────────────────────────────────
# INSERT IN BATCHES
# ─────────────────────────────────────────────
BATCH_SIZE = 5_000


def insert_data(df: pd.DataFrame):
    rows = [
        (
            row.ticker,
            row.series if not pd.isna(row.series) else None,
            row.date.date(),
            float(row.open),
            float(row.high),
            float(row.low),
            float(row.close),
            _nan_or(row.last),
            _nan_or(row.prev_close),
            int(row.volume),
            _nan_or(row.trd_val),
            int(row.trades),
            row.isin if not pd.isna(row.isin) else None,
            # RSI intermediate
            _nan_or(row.delta),
            _nan_or(row.u),
            _nan_or(row.d),
            _nan_or(row.avg_gain),
            _nan_or(row.avg_loss),
            _nan_or(row.rs),
            _nan_or(row.rsi),
            # Banker
            _nan_or(row.raw_banker),
            _nan_or(row.banker_rsi),
            _nan_or(row.banker_ma),
            _nan_or(row.banker_signal),
            None if pd.isna(row.banker_bull) else int(row.banker_bull),
        )
        for row in df.itertuples(index=False)
    ]

    conn     = get_connection()
    cur      = conn.cursor()
    total    = len(rows)
    inserted = 0

    try:
        for i in range(0, total, BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            cur.executemany(INSERT_SQL, batch)
            conn.commit()
            inserted += len(batch)
            print(f"  Inserted {inserted:,} / {total:,} rows...", end="\r")
        print(f"\nDone — {inserted:,} rows upserted into `nse_eod`.")
    except Error as e:
        conn.rollback()
        print(f"\nDB error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=== NSE EOD → MySQL Loader ===\n")
    print(f"DB host   : {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print(f"DB name   : {DB_CONFIG['database']}")
    print(f"EOD folder: {EOD_FOLDER}")
    print(f"Series    : {SERIES_FILTER or 'ALL'}\n")

    # 1. Load all files
    df = load_all_files(EOD_FOLDER)

    # 2. Compute all signals
    print("Computing RSI intermediate + Banker signals...")
    df = add_banker_signals(df)
    print("Signals computed.\n")

    # 3. Setup DB + table
    setup_database()

    # 4. Insert
    print("Inserting into MySQL...")
    insert_data(df)

    print("\n✓ All done!")

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
    pip install pandas mysql-connector-python numpy

Usage:
    1. Update DB_CONFIG below with your credentials.
    2. Set EOD_FOLDER to the folder containing your NSE CSV files.
    3. Optionally set SERIES_FILTER to restrict to specific series (e.g. ["EQ"]).
    4. Run: python nse_to_mysql_with_banker_signal.py
"""

import os
import sys
import glob
import numpy as np
import pandas as pd
import mysql.connector
from mysql.connector import Error

# ─────────────────────────────────────────────
# CONFIGURATION  — edit these
# ─────────────────────────────────────────────
from dotenv import load_dotenv
import os
load_dotenv()

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", "3306")),
    "database": os.getenv("DB_NAME", "nse_eod"),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "use_pure": True,
}

EOD_FOLDER = os.getenv("EOD_FOLDER", "./data")

# Set to a list like ["EQ"] to load only equity series, or None for all series
SERIES_FILTER = ["EQ"]

# ─────────────────────────────────────────────
# MCDX BANKER SIGNAL PARAMETERS (match Pine)
# ─────────────────────────────────────────────
RSI_BASE_BANKER    = 50
RSI_PERIOD_BANKER  = 50
SENSITIVITY_BANKER = 1.5

# How many rows of history to pull from DB per ticker to warm up the RSI
# 50 (RSI period) + 31 (longest MA) + some buffer = 100 is safe
HISTORY_ROWS = 100


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
    rsi_df = compute_rsi_full(close.astype(float), RSI_PERIOD_BANKER)
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
def load_all_files(folder: str, loaded_dates: set = None) -> pd.DataFrame:
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

    if loaded_dates:
        new_files = []
        for f in files:
            base = os.path.basename(f)  # e.g. 20260521_NSE.csv
            date_part = base[:8]        # 20260521
            date_str = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
            if date_str not in loaded_dates:
                new_files.append(f)
            else:
                print(f"Skipping {base} — already in DB")
        files = new_files

    if not files:
        return None

    print(f"Found {len(files)} new NSE file(s).")
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
# FETCH HISTORY FROM DB TO WARM UP RSI
# ─────────────────────────────────────────────
def fetch_history_for_tickers(tickers: list, before_date: str) -> pd.DataFrame:
    """
    For each ticker, pull the last HISTORY_ROWS rows before `before_date`
    from the DB. This gives the RSI computation enough history to produce
    valid banker_rsi values for the new date(s).
    """
    tickers = list(tickers)  # convert numpy array to plain Python list
    if not tickers:
        return pd.DataFrame()

    conn = get_connection()
    cur  = conn.cursor(dictionary=True)

    # Use ROW_NUMBER to get last HISTORY_ROWS per ticker efficiently
    query = f"""
        SELECT ticker, series, trade_date AS date, open, high, low, close,
               last, prev_close, volume, trd_val, trades, isin
        FROM (
            SELECT ticker, series, trade_date, open, high, low, close,
                   last, prev_close, volume, trd_val, trades, isin,
                   ROW_NUMBER() OVER (
                       PARTITION BY ticker
                       ORDER BY trade_date DESC
                   ) AS rn
            FROM nse_eod
            WHERE trade_date < %s
              AND series = 'EQ'
              AND ticker IN ({','.join(['%s'] * len(tickers))})
        ) ranked
        SELECT ticker, trade_date AS date, close
        FROM nse_eod
        WHERE trade_date < %s
            AND series = 'EQ'
            AND ticker IN ({','.join(['%s'] * len(tickers))})
        ORDER BY ticker, trade_date ASC
    """
    all_rows = []
    CHUNK = 200  # fetch 200 tickers at a time

    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i : i + CHUNK]
        placeholders = ','.join(['%s'] * len(chunk))
        query = f"""
            SELECT ticker, series, trade_date AS date, open, high, low, close,
                   last, prev_close, volume, trd_val, trades, isin
            FROM nse_eod
            WHERE trade_date < %s
              AND series = 'EQ'
              AND ticker IN ({placeholders})
            ORDER BY ticker, trade_date ASC
        """
        cur.execute(query, [before_date] + chunk)
        all_rows.extend(cur.fetchall())
        print(f"  Fetched history: {min(i+CHUNK, len(tickers))}/{len(tickers)} tickers...", end="\r")

    cur.close()
    conn.close()

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["date"])

    for col in ["delta", "u", "d", "avg_gain", "avg_loss", "rs", "rsi",
                "raw_banker", "banker_rsi", "banker_ma", "banker_signal", "banker_bull"]:
        df[col] = np.nan

    print(f"\n  Fetched {len(df):,} history rows from DB for {len(tickers):,} tickers.")
    return df


# ─────────────────────────────────────────────
# COMPUTE SIGNALS PER TICKER
# ─────────────────────────────────────────────
def add_banker_signals(df: pd.DataFrame, new_dates: set = None) -> pd.DataFrame:
    """
    Group by ticker, compute all intermediate + final Banker columns,
    then merge back.

    If new_dates is provided, only rows with dates in new_dates are
    returned for upserting — history rows are used only for warm-up.
    """
    results = []
    for ticker, grp in df.groupby("ticker", sort=False):
        grp = grp.copy().sort_values("date").reset_index(drop=True)

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

        # If we have history warm-up rows, only keep the new date rows for insert
        if new_dates:
            grp = grp[grp["date"].dt.strftime("%Y-%m-%d").isin(new_dates)]

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


def get_loaded_dates() -> set:
    """Fetch all trade_dates already in the DB"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT trade_date FROM nse_eod")
        dates = {str(row[0]) for row in cur.fetchall()}
        cur.close()
        conn.close()
        return dates
    except:
        return set()

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

def is_seed_valid(ticker, conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM nse_eod 
        WHERE ticker = %s AND series = 'EQ'
    """, (ticker,))
    count = cur.fetchone()[0]
    return count >= 85  # minimum candles for valid signal

# ─────────────────────────────────────────────
# INSERT IN BATCHES
# ─────────────────────────────────────────────
BATCH_SIZE = 20_000


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

    # 1. Setup DB FIRST, before querying it
    setup_database()

    # 1. Load only new files
    loaded_dates = get_loaded_dates()   # ← comment this out if you want to load all files every time (e.g. during development)
    #loaded_dates = set()                  # ← add this line to ignore loaded dates and reprocess all files (useful during development)
    df = load_all_files(EOD_FOLDER, loaded_dates)
    if df is None:
        print("No new files to process.")
        sys.exit(0)

    # 2. Find new dates and tickers being loaded
    new_dates = set(df["date"].dt.strftime("%Y-%m-%d").unique())
    tickers   = df["ticker"].unique().tolist()
    min_date  = df["date"].min().strftime("%Y-%m-%d")

    # 3. Fetch history from DB to warm up RSI computation
    print(f"Fetching RSI warm-up history for {len(tickers):,} tickers before {min_date}...")
    history_df = fetch_history_for_tickers(tickers, min_date)

    # 4. Combine history (for warm-up) + new rows, sorted by ticker+date
    if not history_df.empty:
        combined = pd.concat([history_df, df], ignore_index=True)
        combined.sort_values(["ticker", "date"], inplace=True)
        combined.reset_index(drop=True, inplace=True)
    else:
        print("  No history found — computing from new data only (first load or new tickers).")
        combined = df

    # 5. Compute all signals on full series (history + new)
    print("Computing RSI intermediate + Banker signals...")
    enriched = add_banker_signals(combined, new_dates=new_dates)
    print(f"Signals computed — {len(enriched):,} new rows to upsert.\n")


    # 7. Insert only the new date rows
    print("Inserting into MySQL...")
    insert_data(enriched)

    print("\n✓ All done!")
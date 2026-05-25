"""
NSE Banker RSI Dashboard API
=============================
Flask backend that queries the nse_eod MySQL table and returns
buy signals based on three criteria:

  1. "immediate"  — banker_rsi > 0 today
  2. "3day"       — banker_rsi == 0 for the 3 days prior, then > 0 today
  3. "5day"       — banker_rsi == 0 for the 5 days prior, then > 0 today

Also exposes banker_bull, banker_ma, and banker_signal from the NSE table.

Run:
    pip install flask flask-cors mysql-connector-python
    python nse_api.py

Endpoints:
    GET /api/dates                        — list of available trade dates (last 60)
    GET /api/signal-day?date=YYYY-MM-DD   — signals for a specific date
    GET /api/signals?days=10              — last N trading days of signal data
    GET /api/health                       — DB connectivity + row count
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector
from collections import defaultdict

app = Flask(__name__)
CORS(app)  # allow React dev server to call this API

from dotenv import load_dotenv
import os
load_dotenv()

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 3306)),
    "database": os.getenv("DB_NAME", "nse_eod"),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "use_pure": True,
}


def get_conn():
    return mysql.connector.connect(**DB_CONFIG)


def dict_cursor(conn):
    return conn.cursor(dictionary=True)


# ── helpers ──────────────────────────────────────────────────────────────────

def get_recent_dates(n: int) -> list[str]:
    """Return the last N distinct trade dates (most recent first)."""
    conn = get_conn()
    cur  = dict_cursor(conn)
    cur.execute(
        "SELECT DISTINCT trade_date FROM nse_eod "
        "ORDER BY trade_date DESC LIMIT %s",
        (n,),
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [str(r["trade_date"]) for r in rows]


def compute_signals_for_date(trade_date: str) -> list[dict]:
    """
    For each ticker (EQ series), fetch only the last 7 rows per ticker
    up to and including trade_date using a SQL window function.
    This avoids pulling millions of rows and filtering in Python.
    """
    conn = get_conn()
    cur  = dict_cursor(conn)

    # Use ROW_NUMBER() to fetch only the 7 most recent rows per ticker.
    # This runs entirely in MySQL — Python receives ~14k rows max instead of millions.
    query = """
        SELECT ticker, series, trade_date, banker_rsi, banker_ma,
               banker_signal, banker_bull, close
        FROM (
            SELECT ticker, series, trade_date, banker_rsi, banker_ma,
                   banker_signal, banker_bull, close,
                   ROW_NUMBER() OVER (
                       PARTITION BY ticker
                       ORDER BY trade_date DESC
                   ) AS rn
            FROM nse_eod
            WHERE trade_date <= %s
              AND banker_rsi IS NOT NULL
              AND series = 'EQ'
        ) ranked
        WHERE rn <= 7
        ORDER BY ticker, trade_date DESC
    """
    cur.execute(query, (trade_date,))
    rows = cur.fetchall()
    cur.close(); conn.close()

    # Group by ticker (already limited to 7 rows each by SQL)
    ticker_rows = defaultdict(list)
    for r in rows:
        ticker_rows[r["ticker"]].append(r)

    results = []
    for ticker, history in ticker_rows.items():
        # history[0] = most recent row (trade_date), history[1..] = prior days
        if not history or str(history[0]["trade_date"]) != trade_date:
            continue  # ticker had no data on this exact date

        today_rsi    = float(history[0]["banker_rsi"])
        today_close  = float(history[0]["close"])
        today_ma     = float(history[0]["banker_ma"])     if history[0]["banker_ma"]     is not None else None
        today_signal = float(history[0]["banker_signal"]) if history[0]["banker_signal"] is not None else None
        today_bull   = bool(history[0]["banker_bull"])    if history[0]["banker_bull"]   is not None else False

        # signal 1: immediate — banker_rsi > 0 today
        immediate = today_rsi > 0

        # signal 2: 3-day — 0 for prior 3 days, >0 today
        three_day = False
        if today_rsi > 0 and len(history) >= 4:
            prior_3 = [float(history[i]["banker_rsi"]) for i in range(1, 4)]
            three_day = all(v == 0 for v in prior_3)

        # signal 3: 5-day — 0 for prior 5 days, >0 today
        five_day = False
        if today_rsi > 0 and len(history) >= 6:
            prior_5 = [float(history[i]["banker_rsi"]) for i in range(1, 6)]
            five_day = all(v == 0 for v in prior_5)

        if immediate or three_day or five_day:
            results.append({
                "ticker":        ticker,
                "series":        history[0]["series"],
                "date":          trade_date,
                "banker_rsi":    round(today_rsi, 4),
                "banker_ma":     round(today_ma, 4)     if today_ma     is not None else None,
                "banker_signal": round(today_signal, 4) if today_signal is not None else None,
                "banker_bull":   today_bull,
                "close":         round(today_close, 4),
                "immediate":     immediate,
                "three_day":     three_day,
                "five_day":      five_day,
                "prior_banker_rsi": [
                    {
                        "date":       str(history[i]["trade_date"]),
                        "banker_rsi": round(float(history[i]["banker_rsi"]), 4),
                    }
                    for i in range(1, min(6, len(history)))
                ],
            })

    # sort: 5day first, then 3day, then immediate-only; within group by ticker
    def rank(r):
        if r["five_day"]:  return 0
        if r["three_day"]: return 1
        return 2

    results.sort(key=lambda r: (rank(r), r["ticker"]))
    return results


# ── routes ────────────────────────────────────────────────────────────────────

@app.route("/api/dates")
def api_dates():
    """Return available trade dates."""
    try:
        dates = get_recent_dates(60)
        return jsonify({"dates": dates})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/signal-day")
def api_signal_day():
    """Return signals for one specific date."""
    date = request.args.get("date")
    if not date:
        return jsonify({"error": "date param required (YYYY-MM-DD)"}), 400
    try:
        signals = compute_signals_for_date(date)
        return jsonify({"date": date, "signals": signals, "count": len(signals)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/signals")
def api_signals():
    """Return signals for the last N trading days."""
    n = int(request.args.get("days", 7))
    try:
        dates = get_recent_dates(n)
        all_results = {}
        for d in dates:
            all_results[d] = compute_signals_for_date(d)
        return jsonify({"data": all_results, "dates": dates})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health")
def health():
    try:
        conn = get_conn()
        cur  = dict_cursor(conn)
        cur.execute("SELECT COUNT(*) as cnt FROM nse_eod LIMIT 1")
        row  = cur.fetchone()
        cur.close(); conn.close()
        return jsonify({"status": "ok", "rows": row["cnt"]})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5001)   # port 5001 so NASDAQ stays on 5000

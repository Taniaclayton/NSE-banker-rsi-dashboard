import { useState, useEffect, useCallback, useMemo } from "react";

const API = import.meta.env.VITE_API_URL || "http://localhost:5001/api";

const BADGE = {
  five_day:  { label: "5-day setup", bg: "#EAF3DE", color: "#3B6D11", border: "#639922",
               darkBg: "#1a3a06", darkColor: "#c0dd97", darkBorder: "#4a7a18" },
  three_day: { label: "3-day setup", bg: "#E6F1FB", color: "#185FA5", border: "#378ADD",
               darkBg: "#0c2f5a", darkColor: "#85b7eb", darkBorder: "#2a6aaa" },
  immediate: { label: "RSI > 0",     bg: "#FAEEDA", color: "#854F0B", border: "#BA7517",
               darkBg: "#3d2200", darkColor: "#fac775", darkBorder: "#8a5010" },
  bull:      { label: "Bull ▲",      bg: "#F0FFF4", color: "#276749", border: "#48BB78",
               darkBg: "#0d3320", darkColor: "#68d391", darkBorder: "#2f855a" },
};

const LIGHT_VARS = `
  --color-background-primary: #ffffff;
  --color-background-secondary: #f1efe8;
  --color-background-info: #e6f1fb;
  --color-background-success: #eaf3de;
  --color-background-danger: #fcebeb;
  --color-background-warning: #faeeda;
  --color-text-primary: #1a1a18;
  --color-text-secondary: #5f5e5a;
  --color-text-info: #185fa5;
  --color-text-success: #3b6d11;
  --color-text-danger: #a32d2d;
  --color-text-warning: #854f0b;
  --color-border-tertiary: rgba(0,0,0,0.10);
  --color-border-secondary: rgba(0,0,0,0.22);
  --color-border-primary: rgba(0,0,0,0.35);
  --color-border-info: #185fa5;
  --font-sans: system-ui, -apple-system, sans-serif;
  --font-mono: ui-monospace, monospace;
  --border-radius-md: 8px;
  --border-radius-lg: 12px;
`;

const DARK_VARS = `
  --color-background-primary: #2c2c2a;
  --color-background-secondary: #232321;
  --color-background-info: #0c447c;
  --color-background-success: #27500a;
  --color-background-danger: #791f1f;
  --color-background-warning: #633806;
  --color-text-primary: #f0ede6;
  --color-text-secondary: #b4b2a9;
  --color-text-info: #85b7eb;
  --color-text-success: #c0dd97;
  --color-text-danger: #f09595;
  --color-text-warning: #fac775;
  --color-border-tertiary: rgba(255,255,255,0.08);
  --color-border-secondary: rgba(255,255,255,0.18);
  --color-border-primary: rgba(255,255,255,0.35);
  --color-border-info: #85b7eb;
  --font-sans: system-ui, -apple-system, sans-serif;
  --font-mono: ui-monospace, monospace;
  --border-radius-md: 8px;
  --border-radius-lg: 12px;
`;

function Badge({ type, dark }) {
  const s = BADGE[type];
  return (
    <span style={{
      fontSize: 11, fontWeight: 500, padding: "2px 8px",
      borderRadius: 4,
      border: `1px solid ${dark ? s.darkBorder : s.border}`,
      background: dark ? s.darkBg : s.bg,
      color: dark ? s.darkColor : s.color,
      whiteSpace: "nowrap",
    }}>
      {s.label}
    </span>
  );
}

function MiniBar({ value, max = 20 }) {
  const pct   = Math.min(100, (value / max) * 100);
  const color = value >= 8.5 ? "#3B6D11" : value > 0 ? "#BA7517" : "#B4B2A9";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{
        width: 64, height: 6, background: "var(--color-background-secondary)",
        borderRadius: 3, overflow: "hidden", flexShrink: 0,
      }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3, transition: "width 0.3s" }} />
      </div>
      <span style={{ fontSize: 12, color: "var(--color-text-secondary)", minWidth: 32 }}>
        {value.toFixed(2)}
      </span>
    </div>
  );
}

function PriorDots({ prior }) {
  return (
    <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
      {prior.map((p, i) => (
        <div key={i} title={`${p.date}: ${p.banker_rsi}`} style={{
          width: 8, height: 8, borderRadius: "50%",
          background: p.banker_rsi > 0 ? "#639922" : "#B4B2A9",
          flexShrink: 0,
        }} />
      ))}
    </div>
  );
}

function SignalRow({ sig, dark }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <tr
        onClick={() => setExpanded(e => !e)}
        style={{ cursor: "pointer", borderBottom: "0.5px solid var(--color-border-tertiary)" }}
      >
        <td style={{ padding: "10px 12px", fontWeight: 500, fontSize: 14, fontFamily: "var(--font-mono)" }}>
          {sig.ticker}
        </td>
        <td style={{ padding: "10px 8px" }}>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {sig.five_day  && <Badge type="five_day"  dark={dark} />}
            {sig.three_day && !sig.five_day  && <Badge type="three_day" dark={dark} />}
            {!sig.five_day && !sig.three_day && sig.immediate && <Badge type="immediate" dark={dark} />}
            {sig.banker_bull && <Badge type="bull" dark={dark} />}
          </div>
        </td>
        <td style={{ padding: "10px 8px" }}>
          <MiniBar value={sig.banker_rsi} />
        </td>
        <td style={{ padding: "10px 8px", fontSize: 13, color: "var(--color-text-secondary)" }}>
          <PriorDots prior={sig.prior_banker_rsi.slice(0, 5)} />
        </td>
        <td style={{ padding: "10px 12px", fontSize: 13, textAlign: "right", color: "var(--color-text-secondary)" }}>
          ₹{sig.close.toFixed(2)}
        </td>
        <td style={{ padding: "10px 8px", fontSize: 16, color: "var(--color-text-secondary)", textAlign: "center" }}>
          {expanded ? "▲" : "▼"}
        </td>
      </tr>

      {expanded && (
        <tr style={{ background: "var(--color-background-secondary)" }}>
          <td colSpan={6} style={{ padding: "10px 16px 14px" }}>
            <div style={{ display: "flex", gap: 32, flexWrap: "wrap" }}>
              <div>
                <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 4 }}>
                  Prior days (newest → oldest)
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {sig.prior_banker_rsi.map((p, i) => (
                    <div key={i} style={{
                      fontSize: 12, padding: "3px 8px", borderRadius: 4,
                      background: p.banker_rsi > 0
                        ? (dark ? "#1a3a06" : "#EAF3DE")
                        : "var(--color-background-primary)",
                      border: "0.5px solid var(--color-border-tertiary)",
                      color: p.banker_rsi > 0
                        ? (dark ? "#c0dd97" : "#3B6D11")
                        : "var(--color-text-secondary)",
                    }}>
                      {p.date.slice(5)}: <strong>{p.banker_rsi.toFixed(2)}</strong>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 4 }}>
                  Banker MA / Signal
                </div>
                <div style={{ display: "flex", gap: 12, fontSize: 13 }}>
                  <span>
                    <span style={{ color: "var(--color-text-secondary)" }}>MA: </span>
                    <strong>{sig.banker_ma != null ? sig.banker_ma.toFixed(4) : "—"}</strong>
                  </span>
                  <span>
                    <span style={{ color: "var(--color-text-secondary)" }}>Signal: </span>
                    <strong>{sig.banker_signal != null ? sig.banker_signal.toFixed(4) : "—"}</strong>
                  </span>
                </div>
              </div>

              <div>
                <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 4 }}>
                  Signal strength
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {sig.five_day    && <Badge type="five_day"  dark={dark} />}
                  {sig.three_day   && <Badge type="three_day" dark={dark} />}
                  {sig.immediate   && <Badge type="immediate" dark={dark} />}
                  {sig.banker_bull && <Badge type="bull"      dark={dark} />}
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function FilterBar({ filter, setFilter, count }) {
  const btn = (key, label) => (
    <button
      onClick={() => setFilter(key)}
      style={{
        fontSize: 12, padding: "5px 12px", borderRadius: 6, cursor: "pointer",
        border: filter === key
          ? "1.5px solid var(--color-border-info)"
          : "0.5px solid var(--color-border-secondary)",
        background: filter === key ? "var(--color-background-info)" : "transparent",
        color:      filter === key ? "var(--color-text-info)"       : "var(--color-text-secondary)",
        fontWeight: filter === key ? 500 : 400,
      }}
    >
      {label}
    </button>
  );
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      {btn("all",       "All signals")}
      {btn("five_day",  "5-day only")}
      {btn("three_day", "3-day only")}
      {btn("immediate", "RSI > 0 only")}
      {btn("bull",      "Bull only")}
      <span style={{ fontSize: 12, color: "var(--color-text-secondary)", marginLeft: 4 }}>
        {count} ticker{count !== 1 ? "s" : ""}
      </span>
    </div>
  );
}

function CopyButton({ label, text, color }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <button onClick={handleCopy} style={{
      fontSize: 12, padding: "5px 12px", borderRadius: 6, cursor: "pointer",
      border: `1px solid ${color}`, background: copied ? color : "transparent",
      color: copied ? "#fff" : color, fontWeight: 500, transition: "all 0.15s",
      whiteSpace: "nowrap",
    }}>
      {copied ? "✓ Copied!" : label}
    </button>
  );
}

function TradingViewPanel({ signals }) {
  const [open, setOpen] = useState(false);

  const lists = {
    five_day:  signals.filter(s => s.five_day).map(s => `NSE:${s.ticker}`).join(","),
    three_day: signals.filter(s => s.three_day && !s.five_day).map(s => `NSE:${s.ticker}`).join(","),
    immediate: signals.filter(s => s.immediate).map(s => `NSE:${s.ticker}`).join(","),
    bull:      signals.filter(s => s.banker_bull).map(s => `NSE:${s.ticker}`).join(","),
  };

  const counts = {
    five_day:  signals.filter(s => s.five_day).length,
    three_day: signals.filter(s => s.three_day && !s.five_day).length,
    immediate: signals.filter(s => s.immediate).length,
    bull:      signals.filter(s => s.banker_bull).length,
  };

  return (
    <div style={{ marginBottom: "0.75rem" }}>
      <button onClick={() => setOpen(o => !o)} style={{
        fontSize: 12, padding: "5px 14px", borderRadius: 6, cursor: "pointer",
        border: "0.5px solid var(--color-border-secondary)", background: "transparent",
        color: "var(--color-text-secondary)", display: "flex", alignItems: "center", gap: 6,
      }}>
        <span>📋</span> TradingView lists {open ? "▲" : "▼"}
      </button>

      {open && (
        <div style={{
          marginTop: 8, padding: "14px 16px", borderRadius: "var(--border-radius-md)",
          border: "0.5px solid var(--color-border-tertiary)",
          background: "var(--color-background-secondary)",
          display: "flex", flexDirection: "column", gap: 12,
        }}>
          <p style={{ fontSize: 12, color: "var(--color-text-secondary)", margin: 0 }}>
            Copy a list and paste it into TradingView's Watchlist import (+ → Import watchlist).
          </p>
          {[
            { key: "five_day",  label: "5-day setups",   color: "#3B6D11" },
            { key: "three_day", label: "3-day setups",   color: "#185FA5" },
            { key: "immediate", label: "All RSI > 0",    color: "#854F0B" },
            { key: "bull",      label: "Bull (RSI>8.5)", color: "#276749" },
          ].map(({ key, label, color }) => (
            <div key={key}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                <span style={{ fontSize: 12, fontWeight: 500, color }}>{label} ({counts[key]})</span>
                {lists[key] && <CopyButton label={`Copy ${label}`} text={lists[key]} color={color} />}
              </div>
              <div style={{
                fontSize: 11, fontFamily: "var(--font-mono)", padding: "6px 10px",
                background: "var(--color-background-primary)", borderRadius: 4,
                border: "0.5px solid var(--color-border-tertiary)",
                color: "var(--color-text-secondary)", wordBreak: "break-all",
                maxHeight: 60, overflowY: "auto", lineHeight: 1.6,
              }}>
                {lists[key] || <em>No tickers</em>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DarkModeToggle({ dark, setDark }) {
  return (
    <button
      onClick={() => setDark(d => !d)}
      title={dark ? "Switch to light mode" : "Switch to dark mode"}
      style={{
        background: "transparent",
        border: "0.5px solid var(--color-border-secondary)",
        borderRadius: 6, cursor: "pointer",
        padding: "5px 10px", fontSize: 16, lineHeight: 1,
        color: "var(--color-text-secondary)",
        transition: "border-color 0.15s",
      }}
    >
      {dark ? "☀️" : "🌙"}
    </button>
  );
}

export default function NseApp() {
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem("nseRsiDark");
    if (saved !== null) return saved === "true";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });

  const [dates,        setDates]        = useState([]);
  const [selectedDate, setSelectedDate] = useState("");
  const [signals,      setSignals]      = useState([]);
  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState(null);
  const [filter,       setFilter]       = useState("all");
  const [search,       setSearch]       = useState("");
  const [health,       setHealth]       = useState(null);
  const [sortCol,      setSortCol]      = useState(null);
  const [sortDir,      setSortDir]      = useState("asc");

  // Persist preference and apply to body
  useEffect(() => {
    localStorage.setItem("nseRsiDark", dark);
    document.body.style.background = dark ? "#1a1a18" : "#f8f8f6";
    document.body.style.color = dark ? "#f0ede6" : "#1a1a18";
  }, [dark]);

  const handleSort = (col) => {
    if (sortCol === col) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortCol(col); setSortDir("asc"); }
  };

  const fetchDates = useCallback((isInitial = false) => {
    fetch(`${API}/dates`)
      .then(r => r.json())
      .then(d => {
        const incoming = d.dates || [];
        setDates(prev => {
          if (incoming.length && incoming[0] !== prev[0]) {
            setSelectedDate(incoming[0]);
          } else if (isInitial && incoming.length) {
            setSelectedDate(incoming[0]);
          }
          return incoming;
        });
      })
      .catch(() => {
        if (isInitial)
          setError("Cannot reach API at localhost:5001 — is the NSE Flask server running?");
      });
    fetch(`${API}/health`)
      .then(r => r.json())
      .then(d => setHealth(d))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchDates(true);
    const id = setInterval(() => fetchDates(false), 60_000);
    return () => clearInterval(id);
  }, [fetchDates]);

  useEffect(() => {
    if (!selectedDate) return;
    setLoading(true);
    setError(null);
    fetch(`${API}/signal-day?date=${selectedDate}`)
      .then(r => r.json())
      .then(d => {
        if (d.error) throw new Error(d.error);
        setSignals(d.signals || []);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [selectedDate]);

  const filtered = useMemo(() => {
    const base = signals.filter(s => {
      const matchFilter =
        filter === "all"       ? true :
        filter === "five_day"  ? s.five_day :
        filter === "three_day" ? (s.three_day && !s.five_day) :
        filter === "immediate" ? (s.immediate && !s.three_day && !s.five_day) :
        filter === "bull"      ? s.banker_bull :
        true;
      const matchSearch = search === "" || s.ticker.toLowerCase().includes(search.toLowerCase());
      return matchFilter && matchSearch;
    });

    if (!sortCol) return base;
    return [...base].sort((a, b) => {
      let av, bv;
      if      (sortCol === "ticker") { av = a.ticker;     bv = b.ticker; }
      else if (sortCol === "rsi")    { av = a.banker_rsi; bv = b.banker_rsi; }
      else if (sortCol === "close")  { av = a.close;      bv = b.close; }
      else if (sortCol === "signal") {
        const rank = s => s.five_day ? 0 : s.three_day ? 1 : 2;
        av = rank(a); bv = rank(b);
      }
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ?  1 : -1;
      return 0;
    });
  }, [signals, filter, search, sortCol, sortDir]);

  const counts = {
    five_day:  signals.filter(s => s.five_day).length,
    three_day: signals.filter(s => s.three_day && !s.five_day).length,
    immediate: signals.filter(s => s.immediate && !s.three_day && !s.five_day).length,
    bull:      signals.filter(s => s.banker_bull).length,
  };

  return (
    <>
      <style>{`:root { ${dark ? DARK_VARS : LIGHT_VARS} }`}</style>

      <div style={{ fontFamily: "var(--font-sans)", padding: "1.5rem", maxWidth: 960 }}>

        {/* Header */}
        <div style={{ marginBottom: "1.5rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4, justifyContent: "space-between" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
              <span style={{ fontSize: 20, fontWeight: 500, color: "var(--color-text-primary)" }}>NSE Banker RSI signals</span>
              {health && health.status === "ok" && (
                <span style={{
                  fontSize: 12, color: "var(--color-text-success)",
                  background: "var(--color-background-success)",
                  padding: "2px 8px", borderRadius: 4,
                }}>
                  DB connected · {health.rows?.toLocaleString()} rows
                </span>
              )}
              {health && health.status === "error" && (
                <span style={{
                  fontSize: 12, color: "var(--color-text-danger)",
                  background: "var(--color-background-danger)",
                  padding: "2px 8px", borderRadius: 4,
                }}>
                  DB error
                </span>
              )}
            </div>
            <DarkModeToggle dark={dark} setDark={setDark} />
          </div>
          <p style={{ fontSize: 14, color: "var(--color-text-secondary)", margin: 0 }}>
            NSE EQ series tickers where banker_rsi crosses from 0 → above 0.
            Three setups: 5-day silent period, 3-day, or immediate. Bull flag = banker_rsi &gt; 8.5.
          </p>
        </div>

        {/* Controls */}
        <div style={{
          display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap",
          marginBottom: "1rem", padding: "12px 16px",
          background: "var(--color-background-secondary)",
          borderRadius: "var(--border-radius-md)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <label style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Date</label>
            <select
              value={selectedDate}
              onChange={e => setSelectedDate(e.target.value)}
              style={{ fontSize: 13, padding: "5px 8px" }}
            >
              {dates.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
          <input
            type="text"
            placeholder="Search ticker…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{ fontSize: 13, padding: "5px 10px", width: 150 }}
          />
        </div>

        {/* Summary cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: "1rem" }}>
          {[
            { key: "five_day",  label: "5-day setups",   color: dark ? "#c0dd97" : "#3B6D11" },
            { key: "three_day", label: "3-day setups",   color: dark ? "#85b7eb" : "#185FA5" },
            { key: "immediate", label: "RSI > 0 only",   color: dark ? "#fac775" : "#854F0B" },
            { key: "bull",      label: "Bull (RSI>8.5)", color: dark ? "#68d391" : "#276749" },
          ].map(card => (
            <div
              key={card.key}
              onClick={() => setFilter(f => f === card.key ? "all" : card.key)}
              style={{
                padding: "12px 16px", borderRadius: "var(--border-radius-md)",
                background: "var(--color-background-secondary)", cursor: "pointer",
                border: filter === card.key
                  ? `1.5px solid ${card.color}`
                  : "0.5px solid var(--color-border-tertiary)",
              }}
            >
              <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 4 }}>{card.label}</div>
              <div style={{ fontSize: 24, fontWeight: 500, color: card.color }}>{counts[card.key]}</div>
            </div>
          ))}
        </div>

        {/* Filter bar */}
        <div style={{ marginBottom: "0.75rem" }}>
          <FilterBar filter={filter} setFilter={setFilter} count={filtered.length} />
        </div>

        {/* TradingView panel */}
        <TradingViewPanel signals={signals} />

        {/* Error */}
        {error && (
          <div style={{
            padding: "12px 16px", borderRadius: "var(--border-radius-md)",
            background: "var(--color-background-danger)", color: "var(--color-text-danger)",
            fontSize: 14, marginBottom: "1rem",
          }}>
            {error}
          </div>
        )}

        {/* Table */}
        <div style={{
          border: "0.5px solid var(--color-border-tertiary)",
          borderRadius: "var(--border-radius-lg)", overflow: "hidden",
        }}>
          <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
            <colgroup>
              <col style={{ width: "13%" }} />
              <col style={{ width: "27%" }} />
              <col style={{ width: "20%" }} />
              <col style={{ width: "16%" }} />
              <col style={{ width: "16%" }} />
              <col style={{ width: "8%"  }} />
            </colgroup>
            <thead>
              <tr style={{
                background: "var(--color-background-secondary)",
                borderBottom: "0.5px solid var(--color-border-tertiary)",
              }}>
                {[
                  { label: "Ticker",       col: "ticker", align: "left"   },
                  { label: "Signal",       col: "signal", align: "left"   },
                  { label: "Banker RSI",   col: "rsi",    align: "left"   },
                  { label: "Prior 5 days", col: null,     align: "left"   },
                  { label: "Close (₹)",    col: "close",  align: "right"  },
                  { label: "",             col: null,     align: "center" },
                ].map((h, i) => (
                  <th key={i}
                    onClick={() => h.col && handleSort(h.col)}
                    style={{
                      padding: "8px 12px", fontSize: 11, fontWeight: 500,
                      textAlign: h.align,
                      color: sortCol === h.col ? "var(--color-text-primary)" : "var(--color-text-secondary)",
                      textTransform: "uppercase", letterSpacing: "0.05em",
                      cursor: h.col ? "pointer" : "default",
                      userSelect: "none", whiteSpace: "nowrap",
                    }}
                  >
                    {h.label}
                    {h.col && (
                      <span style={{ marginLeft: 4, opacity: sortCol === h.col ? 1 : 0.3, fontSize: 10 }}>
                        {sortCol === h.col ? (sortDir === "asc" ? "▲" : "▼") : "⇅"}
                      </span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={6} style={{ padding: 32, textAlign: "center", color: "var(--color-text-secondary)", fontSize: 14 }}>
                  Loading…
                </td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={6} style={{ padding: 32, textAlign: "center", color: "var(--color-text-secondary)", fontSize: 14 }}>
                  No signals for {selectedDate} with current filter.
                </td></tr>
              ) : (
                filtered.map(sig => <SignalRow key={sig.ticker} sig={sig} dark={dark} />)
              )}
            </tbody>
          </table>
        </div>

        {/* Legend */}
        <div style={{ marginTop: "1rem", display: "flex", gap: 16, flexWrap: "wrap" }}>
          <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "#639922", marginRight: 4 }} />
            banker_rsi &gt; 0
          </span>
          <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "#B4B2A9", marginRight: 4 }} />
            banker_rsi = 0
          </span>
          <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            Bull ▲ = banker_rsi &gt; 8.5 (strong confirmation)
          </span>
          <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            Click any row to expand prior days &amp; MA/Signal values
          </span>
        </div>
      </div>
    </>
  );
}
# utils/db.py
import os, sqlite3, json, time
from contextlib import contextmanager
from typing import Any, Dict

USE_DB = os.getenv("USE_DB","0").lower() in ("1","true","yes","on")
DB_URL = os.getenv("DATABASE_URL","sqlite:////app/data/algogpt.db")

def _path_from_url(url: str) -> str:
    # sqlite:////abs/path.db  -> /abs/path.db
    return url.replace("sqlite:////", "/")

@contextmanager
def _conn():
    if not USE_DB:
        yield None
        return
    path = _path_from_url(DB_URL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, isolation_level=None)
    try:
        yield con
    finally:
        con.close()

def init():
    if not USE_DB: return
    with _conn() as con:
        cur = con.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS alerts (
          id TEXT PRIMARY KEY,
          ts REAL NOT NULL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          entry REAL NOT NULL,
          sl REAL NOT NULL,
          tp1 REAL,
          tp2 REAL,
          tp3 REAL,
          approved INTEGER DEFAULT 0,
          note TEXT
        );

        CREATE TABLE IF NOT EXISTS orders (
          id TEXT PRIMARY KEY,
          ts REAL NOT NULL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          qty REAL NOT NULL,
          price REAL,
          position_side TEXT,
          source TEXT,
          raw TEXT
        );

        CREATE TABLE IF NOT EXISTS positions (
          id TEXT PRIMARY KEY,
          ts_open REAL NOT NULL,
          ts_close REAL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          qty REAL NOT NULL,
          entry REAL,
          exit REAL,
          pnl REAL,
          status TEXT
        );

        CREATE TABLE IF NOT EXISTS tf_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          symbol TEXT NOT NULL,
          interval TEXT NOT NULL,
          timestamp REAL NOT NULL,
          indicators TEXT NOT NULL,
          alignment_status TEXT,
          created_at REAL DEFAULT (strftime('%s', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_tf_snapshots_symbol_interval ON tf_snapshots(symbol, interval);
        CREATE INDEX IF NOT EXISTS idx_tf_snapshots_timestamp ON tf_snapshots(timestamp);

        CREATE TABLE IF NOT EXISTS bt_runs (
          id TEXT PRIMARY KEY,
          strategy TEXT NOT NULL,
          start_date TEXT NOT NULL,
          end_date TEXT NOT NULL,
          folds INTEGER NOT NULL,
          created_at REAL DEFAULT (strftime('%s', 'now')),
          status TEXT DEFAULT 'running',
          summary_json TEXT
        );

        CREATE TABLE IF NOT EXISTS bt_results (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          bt_run_id TEXT NOT NULL,
          symbol TEXT,
          regime TEXT,
          winrate REAL,
          avg_rr REAL,
          expectancy REAL,
          max_dd REAL,
          sample_n INTEGER,
          FOREIGN KEY (bt_run_id) REFERENCES bt_runs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_bt_results_run_id ON bt_results(bt_run_id);
        CREATE INDEX IF NOT EXISTS idx_bt_results_symbol_regime ON bt_results(symbol, regime);

        CREATE TABLE IF NOT EXISTS live_kpis (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          day TEXT NOT NULL UNIQUE,
          winrate_7d REAL,
          winrate_30d REAL,
          exp_rr_30d REAL,
          dd_7d REAL,
          consec_sl INTEGER,
          updated_at REAL DEFAULT (strftime('%s', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_live_kpis_day ON live_kpis(day);

        CREATE TABLE IF NOT EXISTS blocks_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          reason TEXT NOT NULL,
          ctx_json TEXT,
          created_at REAL DEFAULT (strftime('%s', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_blocks_log_created_at ON blocks_log(created_at);
        """)
        con.commit()

def insert_alert(row: Dict[str, Any]):
    if not USE_DB: return
    with _conn() as con:
        cur = con.cursor()
        cur.execute("""INSERT OR REPLACE INTO alerts
          (id, ts, symbol, side, entry, sl, tp1, tp2, tp3, approved, note)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            row.get("id"),
            row.get("ts", time.time()),
            row["symbol"], row["side"], float(row["entry"]), float(row["sl"]),
            row.get("tp1"), row.get("tp2"), row.get("tp3"),
            1 if row.get("approved") else 0,
            row.get("note")
        ))
        con.commit()

def insert_order(row: Dict[str, Any]):
    if not USE_DB: return
    with _conn() as con:
        cur = con.cursor()
        cur.execute("""INSERT OR REPLACE INTO orders
          (id, ts, symbol, side, qty, price, position_side, source, raw)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            row.get("id"),
            row.get("ts", time.time()),
            row["symbol"], row["side"], float(row["qty"]),
            row.get("price"),
            row.get("position_side"),
            row.get("source","system"),
            json.dumps(row.get("raw", {}))
        ))
        con.commit()

def insert_position(row: Dict[str, Any]):
    if not USE_DB: return
    with _conn() as con:
        cur = con.cursor()
        cur.execute("""INSERT OR REPLACE INTO positions
          (id, ts_open, ts_close, symbol, side, qty, entry, exit, pnl, status)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            row.get("id"),
            row.get("ts_open", time.time()),
            row.get("ts_close"),
            row["symbol"], row["side"], float(row["qty"]),
            row.get("entry"), row.get("exit"), row.get("pnl"),
            row.get("status","OPEN")
        ))
        con.commit()

def insert_tf_snapshot(row: Dict[str, Any]):
    """
    Insert multi-timeframe snapshot into database.
    
    Args:
        row: Dict with symbol, interval, timestamp, indicators, alignment_status
    """
    if not USE_DB: return
    with _conn() as con:
        cur = con.cursor()
        cur.execute("""INSERT INTO tf_snapshots
          (symbol, interval, timestamp, indicators, alignment_status)
          VALUES (?, ?, ?, ?, ?)""", (
            row["symbol"],
            row["interval"],
            row.get("timestamp", time.time()),
            json.dumps(row.get("indicators", {})),
            row.get("alignment_status", "UNKNOWN")
        ))
        con.commit()

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

# utils/db_health.py
from __future__ import annotations
import os, sqlite3

def check_db_ready(timeout: float = 0.5) -> dict:
    # SQLite path (אם אין—skip בשקט)
    path = os.getenv("SQLITE_PATH", "").strip()
    if not path:
        return {"ok": True, "skipped": True, "reason": "no_db"}
    try:
        con = sqlite3.connect(path, timeout=timeout, check_same_thread=False)
        try:
            cur = con.cursor()
            cur.execute("PRAGMA schema_version;")
            cur.fetchone()
            return {"ok": True, "skipped": False}
        finally:
            con.close()
    except Exception as e:
        return {"ok": False, "skipped": False, "error": str(e)}


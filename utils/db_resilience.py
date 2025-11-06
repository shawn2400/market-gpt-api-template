# utils/db_resilience.py
from __future__ import annotations
import os
import time
import json
import logging
import pathlib
import threading
from typing import Optional, Any, Iterable

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore
    dict_row = None  # type: ignore

log = logging.getLogger(__name__)


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _geti(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _getf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


class DB:
    """
    Production-grade Database Resilience Layer with:
    - Connection with exponential backoff retries
    - Fallback queue (JSON) when DB offline
    - Periodic health checks & resync
    """

    def __init__(self):
        # Neon Database connection params
        self.host = _get("DB_HOST") or _get("PGHOST")
        self.port = _geti("DB_PORT", 5432) or _geti("PGPORT", 5432)
        self.user = _get("DB_USER") or _get("PGUSER")
        self.password = _get("DB_PASSWORD") or _get("PGPASSWORD")
        self.dbname = _get("DB_NAME") or _get("PGDATABASE")
        self.sslmode = _get("DB_SSLMODE", "require")

        # Connection & retry settings
        self.connect_timeout = _geti("DB_CONNECT_TIMEOUT_SEC", 8)
        self.first_query_timeout = _geti("DB_FIRST_QUERY_TIMEOUT_SEC", 12)
        self.startup_retries = _geti("DB_STARTUP_RETRIES", 8)
        self.startup_backoff_ms = _geti("DB_STARTUP_BACKOFF_MS", 400)

        # Connection pool
        self.pool_min = _geti("DB_POOL_MIN", 1)
        self.pool_max = _geti("DB_POOL_MAX", 8)

        # Fallback queue
        self.fb_enable = _get("DB_FALLBACK_ENABLE", "1") not in ("0", "false", "False", "")
        self.fb_path = _get("DB_FALLBACK_PATH", "static/cache/db_offline_queue.jsonl")
        pathlib.Path(self.fb_path).parent.mkdir(parents=True, exist_ok=True)

        # Internal state
        self._conn: Optional[Any] = None
        self._lock = threading.Lock()

    def dsn(self) -> str:
        """Build PostgreSQL connection string."""
        return (
            f"host={self.host} port={self.port} dbname={self.dbname} "
            f"user={self.user} password={self.password} sslmode={self.sslmode} "
            f"connect_timeout={self.connect_timeout}"
        )

    def connect_with_backoff(self) -> Any:
        """
        Connect to Neon Database with exponential backoff.
        Handles Neon auto-pause wake-up gracefully.
        """
        if not psycopg:
            raise RuntimeError("psycopg is not installed. Run: pip install psycopg[binary]>=3.2.1")

        last_err: Optional[Exception] = None
        for i in range(self.startup_retries):
            try:
                conn = psycopg.connect(self.dsn(), autocommit=True, row_factory=dict_row)
                # First ping (may be slow if Neon endpoint is waking up)
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                self._conn = conn
                log.info(f"DB connected successfully (attempt {i + 1}/{self.startup_retries})")
                return conn
            except Exception as e:
                last_err = e
                delay = (self.startup_backoff_ms * (i + 1)) / 1000.0
                log.warning(f"DB connect retry {i + 1}/{self.startup_retries}: {e} (sleep {delay:.2f}s)")
                time.sleep(delay)
        raise RuntimeError(f"DB connection failed after {self.startup_retries} retries: {last_err}")

    def get_conn(self) -> Any:
        """Get or create database connection."""
        with self._lock:
            if self._conn is None or self._conn.closed:
                self.connect_with_backoff()
            return self._conn

    def exec(self, sql: str, params: Optional[Iterable[Any]] = None) -> int:
        """
        Execute SQL statement (INSERT/UPDATE/DELETE).
        Falls back to JSON queue if DB offline.
        """
        try:
            conn = self.get_conn()
            with conn.cursor() as cur:
                cur.execute(sql, params or [])
                return cur.rowcount or 0
        except Exception as e:
            if self.fb_enable:
                self._enqueue_fallback({"sql": sql, "params": list(params or [])})
                log.error(f"DB offline → queued fallback ({self.fb_path}). err={e}")
                return 0
            raise

    def query(self, sql: str, params: Optional[Iterable[Any]] = None) -> list[dict]:
        """Execute SELECT query and return results as list of dicts."""
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, params or [])
            return list(cur.fetchall())

    def _enqueue_fallback(self, item: dict) -> None:
        """Append failed operation to fallback queue (JSONL)."""
        with self._lock:
            with open(self.fb_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def resync_fallback(self, batch: int = 500) -> int:
        """
        Replay queued operations from fallback file back to DB.
        Best-effort, not transactional.
        """
        path = pathlib.Path(self.fb_path)
        if not path.exists() or path.stat().st_size == 0:
            return 0
        applied = 0
        tmp = path.with_suffix(".jsonl.tmp")
        path.replace(tmp)
        with open(tmp, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    self.exec(item["sql"], item.get("params"))
                    applied += 1
                except Exception as e:
                    # Return to queue if failed - don't lose data
                    with open(self.fb_path, "a", encoding="utf-8") as w:
                        w.write(line)
                if applied >= batch:
                    break
        # Clean up temp file
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return applied


# Global singleton instance
DB_SINGLETON = DB()


def periodic_health_and_resync():
    """
    Background thread: periodic DB health check + resync fallback queue.
    Keeps Neon endpoint alive and syncs queued operations.
    """
    from threading import Event

    stop = Event()
    interval = _geti("DB_RESYNC_INTERVAL_SEC", 45)
    while not stop.wait(interval):
        try:
            DB_SINGLETON.get_conn()
            applied = DB_SINGLETON.resync_fallback(batch=_geti("DB_RESYNC_BATCH", 500))
            if applied:
                log.info(f"DB resync applied {applied} queued ops")
        except Exception as e:
            log.warning(f"DB health/resync loop: {e}")

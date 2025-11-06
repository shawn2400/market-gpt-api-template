# utils/db_bootstrap.py
import logging
from utils.db_resilience import DB_SINGLETON

log = logging.getLogger(__name__)

DDL_HEARTBEAT = """
CREATE TABLE IF NOT EXISTS app_heartbeat(
  id BIGSERIAL PRIMARY KEY,
  at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  note TEXT
);
"""


def bootstrap_schema():
    """
    Initialize database schema on startup.
    Creates heartbeat table for health monitoring.
    """
    try:
        db = DB_SINGLETON
        db.exec(DDL_HEARTBEAT)
        db.exec("INSERT INTO app_heartbeat(note) VALUES (%s)", ["boot"])
        log.info("✅ DB bootstrap OK (heartbeat ready)")
    except Exception as e:
        log.warning(f"⚠️ DB bootstrap failed (may be offline): {e}")

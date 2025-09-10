# routes/executor_status.py
from __future__ import annotations
from fastapi import APIRouter
from utils.runtime_counters import executor_status, ops_debug_state

router = APIRouter(prefix="/executor", tags=["status"])

@router.get("/status")
def exec_status():
    """
    מטריקות טיק של האקסקיוטר:
    - tick_ewma_ms / p95 / p99
    - timeouts_recent_count (window)
    - trades_sent_total
    - last_interval_sec / no_trade_streak
    - degrade_active / leverage_cap / reason / bumps
    """
    return {"ok": True, **executor_status()}

@router.get("/ops", include_in_schema=False)
def ops_debug():
    """דאמפ מלא למעקב מהיר (לא מוצג ב-OpenAPI)."""
    return {"ok": True, **ops_debug_state()}



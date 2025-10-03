# routes/ops_digest.py
from __future__ import annotations
import os
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Query

log = logging.getLogger("algogpt.routes.ops_digest")
router = APIRouter(prefix="/ops/digest", tags=["ops-digest"])

# --- תלות רכה בנוטיפיקציות טלגרם (run-now) ---
try:
    from utils.telegram_notifier_core import send_ops_digest_now as _send_ops_digest_now  # type: ignore
except Exception:
    async def _send_ops_digest_now(hours: Optional[int] = None) -> None:
        log.info({"event": "digest.send.noop", "reason": "telegram_notifier_core_missing", "hours": hours})
        await asyncio.sleep(0)

# --- ניהול ה-job המחזורי ---
from utils.approvals_digest_job import (
    start_expired_digest_job,
    stop_expired_digest_job,
    is_running,
)

def _env_lookback_default() -> Optional[int]:
    try:
        v = os.getenv("OPS_DIGEST_LOOKBACK_HOURS") or os.getenv("OPS_DIGEST_INTERVAL_HOURS", "3")
        return int(float(v))
    except Exception:
        return None

@router.get("/status")
async def digest_status():
    return {
        "ok": True,
        "running": is_running(),
    }

@router.post("/start")
async def digest_start():
    t = start_expired_digest_job()
    return {
        "ok": True,
        "started": bool(t),
        "running": is_running(),
    }

@router.post("/stop")
async def digest_stop():
    stopped = await stop_expired_digest_job()
    return {
        "ok": True,
        "stopped": stopped,
        "running": is_running(),
    }

@router.post("/run-now")
async def digest_run_now(hours: Optional[int] = Query(default=None, ge=1, description="Lookback hours")):
    if hours is None:
        hours = _env_lookback_default()
    await _send_ops_digest_now(hours)
    return {"ok": True, "run_now": True, "hours": hours}

# תחזוקת התאימות: אליאס לנתיב היסטורי
@router.get("/expired")
async def digest_run_expired_alias(hours: Optional[int] = Query(default=None, ge=1)):
    if hours is None:
        hours = _env_lookback_default()
    await _send_ops_digest_now(hours)
    return {"ok": True, "run_now": True, "hours": hours, "alias": "expired"}


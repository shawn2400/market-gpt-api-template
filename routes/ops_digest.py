# -*- coding: utf-8 -*-
# routes/ops_digest.py
from __future__ import annotations
import os
import asyncio
import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, Query

log = logging.getLogger("algogpt.routes.ops_digest")
router = APIRouter(prefix="/ops/digest", tags=["ops-digest"])

# ── soft dep: telegram notifier (send-now) ─────────────────────────────────────
try:
    from utils.telegram_notifier_core import send_ops_digest_now as _impl_send_ops_digest_now  # type: ignore
    _HAS_SEND_IMPL = True
except Exception:
    _HAS_SEND_IMPL = False

async def _send_ops_digest_now(hours: Optional[int] = None) -> Dict[str, Any]:
    """
    Unified shim that always accepts `hours` (fixes TypeError from older code).
    Delegates to real impl if available, otherwise returns a noop-ok response.
    """
    if hours is None:
        try:
            v = os.getenv("OPS_DIGEST_LOOKBACK_HOURS") or os.getenv("OPS_DIGEST_INTERVAL_HOURS", "3")
            hours = int(float(v))
        except Exception:
            hours = None
    if _HAS_SEND_IMPL:
        try:
            return await _impl_send_ops_digest_now(hours)  # type: ignore[arg-type]
        except TypeError:
            # old impl without parameter
            await _impl_send_ops_digest_now()  # type: ignore[misc]
            return {"ok": True, "impl": "legacy", "hours": hours}
        except Exception as e:
            log.exception("digest.send.failed: %s", e)
            return {"ok": False, "error": f"{e}", "hours": hours}
    # fallback noop
    log.info({"event": "digest.send.noop", "reason": "impl_missing", "hours": hours})
    await asyncio.sleep(0)
    return {"ok": True, "impl": "shim", "hours": hours}

# ── periodic job control (optional) ───────────────────────────────────────────
try:
    from utils.approvals_digest_job import (
        start_expired_digest_job,
        stop_expired_digest_job,
        is_running,
    )  # type: ignore
    _HAS_JOB_IMPL = True
except Exception:
    _HAS_JOB_IMPL = False
    def start_expired_digest_job():  # type: ignore
        return None
    async def stop_expired_digest_job():  # type: ignore
        return False
    def is_running() -> bool:  # type: ignore
        return False

# ── routes ────────────────────────────────────────────────────────────────────
@router.get("/status", summary="Digest job status")
async def digest_status():
    return {"ok": True, "running": bool(is_running())}

@router.post("/start", summary="Start periodic digest job")
async def digest_start():
    t = start_expired_digest_job()
    return {"ok": True, "started": bool(t), "running": bool(is_running()), "has_impl": _HAS_JOB_IMPL}

@router.post("/stop", summary="Stop periodic digest job")
async def digest_stop():
    stopped = await stop_expired_digest_job()
    return {"ok": True, "stopped": bool(stopped), "running": bool(is_running()), "has_impl": _HAS_JOB_IMPL}

@router.post("/run-now", summary="Send ops digest now; optional lookback hours")
async def digest_run_now(hours: Optional[int] = Query(default=None, ge=1, description="Lookback hours")):
    res = await _send_ops_digest_now(hours)
    return {"ok": bool(res.get("ok", True)), "run_now": True, "hours": res.get("hours"), "impl": res.get("impl")}

# historical alias: GET /ops/digest/expired?hours=6
@router.get("/expired", summary="Alias for run-now with hours (historical)")
async def digest_run_expired_alias(hours: Optional[int] = Query(default=None, ge=1)):
    res = await _send_ops_digest_now(hours)
    return {"ok": bool(res.get("ok", True)), "run_now": True, "hours": res.get("hours"), "impl": res.get("impl"), "alias": "expired"}

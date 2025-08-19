# routes/health.py
from __future__ import annotations
from datetime import datetime, timezone
import os
from fastapi import APIRouter

router = APIRouter(tags=["Health"])

_BOOT_TS = int(datetime.now(tz=timezone.utc).timestamp())

@router.get("/health", operation_id="getBasicHealth")
def health():
    return {
        "status": "ok",
        "version": os.getenv("ALGOGPT_VERSION", "unknown"),
    }

@router.get("/health/live", operation_id="getLiveness")
def liveness():
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "status": "live",
        "uptime_sec": int(datetime.now(tz=timezone.utc).timestamp()) - _BOOT_TS,
        "now_utc": now,
    }

@router.get("/health/strategy-version", operation_id="getStrategyVersion")
def strategy_version():
    return {
        "ok": True,
        "ALGOGPT_VERSION": os.getenv("ALGOGPT_VERSION"),
        "STRATEGY_VERSION": os.getenv("STRATEGY_VERSION"),
        "GIT_COMMIT": os.getenv("GIT_COMMIT"),
        "REQ_HASH": os.getenv("REQ_HASH"),
    }













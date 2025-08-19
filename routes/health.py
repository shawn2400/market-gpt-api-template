# routes/health.py
from __future__ import annotations
from datetime import datetime, timezone
import os
from fastapi import APIRouter

router = APIRouter(tags=["Health"])
_BOOT = int(datetime.now(tz=timezone.utc).timestamp())

@router.get("/health", operation_id="getBasicHealth")
def health():
    return {"status": "ok", "version": os.getenv("ALGOGPT_VERSION", "unknown")}

@router.get("/health/live", operation_id="getLiveness")
def liveness():
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "status": "live",
        "uptime_sec": int(datetime.now(tz=timezone.utc).timestamp()) - _BOOT,
        "now_utc": now,
    }














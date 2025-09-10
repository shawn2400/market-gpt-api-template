# routes/ws_user_status.py
from __future__ import annotations
import time
from fastapi import APIRouter

try:
    from utils.runtime_counters import ws_get_counters
except Exception:
    def ws_get_counters():  # fallback רזה אם המודול לא נטען
        return {}

router = APIRouter(prefix="/ws-user", tags=["ws-user"])

@router.get("/ping", include_in_schema=False)
async def ping():
    c = {}
    try:
        c = ws_get_counters()
    except Exception:
        pass
    return {
        "ok": True,
        "ts_ms": int(time.time() * 1000),
        "up": bool(c.get("up")) if c else None,
    }

@router.get("/status")
async def status():
    try:
        counters = ws_get_counters()
    except Exception:
        counters = {}
    return {"ok": True, **counters}






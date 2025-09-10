# routes/ws_user_status.py
from __future__ import annotations
from fastapi import APIRouter
from utils.runtime_counters import ws_user_status
try:
    from utils import ws_user_stream
    _have_ws = True
except Exception:
    _have_ws = False

router = APIRouter(prefix="/ws-user", tags=["status"])

@router.get("/status")
def get_ws_user_status():
    counters = ws_user_status()
    extra = {}
    if _have_ws and hasattr(ws_user_stream, "status"):
        try:
            extra = ws_user_stream.status()
        except Exception:
            extra = {}
    return {"ok": True, "counters": counters, "stream": extra}


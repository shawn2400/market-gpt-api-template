from __future__ import annotations
import time
from typing import Any, Dict
from fastapi import APIRouter

router = APIRouter(prefix="", tags=["status"])

# runtime counters (WS)
try:
    from utils.runtime_counters import ws_status
except Exception:
    def ws_status() -> Dict[str, Any]:
        return {}

# optional: local WS user-stream status()
try:
    from utils import ws_user_stream  # has status(): Dict[str, Any]
except Exception:
    ws_user_stream = None  # type: ignore

@router.get("/ws-user/status")
async def get_ws_user_status():
    out: Dict[str, Any] = {
        "ts": int(time.time()),
        "runtime": ws_status(),  # EWMA latency, reconnects, ws_up וכו'
    }
    if ws_user_stream and hasattr(ws_user_stream, "status"):
        try:
            out["stream"] = ws_user_stream.status()  # running/have_listen_key/ws_up (Gauge)
        except Exception:
            out["stream"] = {"running": False, "have_listen_key": False, "ws_up": 0}
    return out




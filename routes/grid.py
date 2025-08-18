# routes/grid.py
from __future__ import annotations

import inspect
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

# Auth
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        raise HTTPException(status_code=401, detail="Unauthorized")

# Optional tracker
try:
    from utils.grid_tracker import get_status as _get_status  # type: ignore
    _HAS_TRACKER = True
except Exception:
    _get_status = None
    _HAS_TRACKER = False

router = APIRouter(
    prefix="/grid",
    tags=["Health"],
    dependencies=[Depends(require_bearer_token)],
)

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()

async def _fetch_tracker_status(detailed: bool) -> Dict[str, Any]:
    if not (_HAS_TRACKER and _get_status):
        return {}
    try:
        sig = None
        try:
            sig = inspect.signature(_get_status)  # type: ignore
        except Exception:
            sig = None

        if sig and any(p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY) and p.name == "detailed"
                       for p in sig.parameters.values()):
            res = _get_status(detailed=detailed)  # type: ignore
        else:
            res = _get_status()  # type: ignore

        if inspect.isawaitable(res):
            res = await res  # type: ignore

        return res if isinstance(res, dict) else {}
    except Exception:
        return {}

def _binance_probe() -> Dict[str, Any]:
    has_api = bool((os.getenv("BINANCE_API_KEY") or "").strip())
    has_sec = bool((os.getenv("BINANCE_API_SECRET") or "").strip())
    fut_ok = False
    fut_err: Optional[str] = None
    if has_api and has_sec:
        try:
            from utils.binance_client import futures_ping  # type: ignore
            futures_ping()
            fut_ok = True
        except Exception as e:
            fut_err = str(e)[:400]
    return {
        "binance_keys": bool(has_api and has_sec),
        "api_present": has_api,
        "secret_present": has_sec,
        "futures_access": fut_ok,
        "futures_error": fut_err,
    }

@router.get("/status", summary="Grid status (workers/queue/concurrency)", operation_id="getGridStatus")
async def grid_status(detailed: bool = Query(False)) -> Dict[str, Any]:
    now_iso = _iso(datetime.now(timezone.utc))

    base: Dict[str, Any] = {
        "ok": True,
        "running": False,
        "workers": 0,
        "queue_size": 0,
        "concurrency": int(os.getenv("GRID_CONCURRENCY", "16")),
        "last_heartbeat": now_iso,
    }

    tracker = await _fetch_tracker_status(detailed=detailed)
    payload: Dict[str, Any] = {**base, **(tracker or {})}

    # normalize
    payload["last_heartbeat"] = payload.get("last_heartbeat") or now_iso
    payload.setdefault("workers", 0)
    payload.setdefault("queue_size", 0)
    payload.setdefault("running", bool(payload.get("workers", 0) or payload.get("queue_size", 0)))
    payload["ok"] = bool(payload.get("ok", True))

    # Binance connectivity snapshot
    payload.update(_binance_probe())
    return payload















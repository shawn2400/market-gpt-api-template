# routes/grid.py
from __future__ import annotations
import inspect
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import os

from fastapi import APIRouter, Depends, HTTPException, Query

# ---- Auth (Bearer) ---------------------------------------------------------
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        raise HTTPException(status_code=401, detail="Unauthorized")

# ---- Optional tracker ------------------------------------------------------
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

def _to_iso_from_any(v: Any) -> Optional[str]:
    try:
        if v is None:
            return None
        if isinstance(v, datetime):
            return _iso(v)
        if isinstance(v, (int, float)):
            return _iso(datetime.fromtimestamp(float(v), tz=timezone.utc))
        if isinstance(v, str):
            return v
    except Exception:
        return None
    return None

async def _fetch_tracker_status(detailed: bool) -> Dict[str, Any]:
    if not (_HAS_TRACKER and _get_status):
        return {}
    try:
        sig = None
        try:
            sig = inspect.signature(_get_status)  # type: ignore
        except Exception:
            sig = None

        if sig and any(p.name == "detailed" for p in sig.parameters.values()):
            res = _get_status(detailed=detailed)  # type: ignore
        else:
            res = _get_status()  # type: ignore

        if inspect.isawaitable(res):
            res = await res  # type: ignore

        return res if isinstance(res, dict) else {}
    except Exception:
        return {}

def _binance_env() -> Dict[str, Any]:
    api = (os.getenv("BINANCE_API_KEY") or "").strip()
    sec = (os.getenv("BINANCE_API_SECRET") or "").strip()
    return {
        "binance_keys": bool(api and sec),
        "api_present": bool(api),
        "secret_present": bool(sec),
    }

async def _check_futures_access() -> Dict[str, Any]:
    """
    מוודא שחשבון FUTURES נגיש. לא נכשל—מחזיר סטטוס.
    לא מבצע פעולות מסוכנות (רק ping/קריאות מידע).
    """
    out = {"futures_access": False, "futures_error": None}
    try:
        # טעינה דחויה כדי לא לקרוס אם המודול לא קיים
        from utils.binance_client import get_futures_client  # type: ignore
    except Exception as e:
        out["futures_error"] = f"binance_client_missing: {e}"
        return out

    try:
        client = get_futures_client()
        # קריאות קלות
        # אם אין הרשאות, הספריה תזרוק חריגה
        if hasattr(client, "futures_ping"):
            rp = client.futures_ping()
            if inspect.isawaitable(rp):
                await rp
        if hasattr(client, "futures_account_balance"):
            rb = client.futures_account_balance()
            if inspect.isawaitable(rb):
                await rb
        out["futures_access"] = True
        return out
    except Exception as e:
        out["futures_error"] = str(e)
        return out

@router.get(
    "/status",
    summary="Grid status (workers/queue/concurrency) + Binance diagnostics",
    operation_id="getGridStatus",
)
async def grid_status(
    detailed: bool = Query(False, description="Include tracker-specific fields when available.")
) -> Dict[str, Any]:
    now_iso = _iso(datetime.now(timezone.utc))

    base: Dict[str, Any] = {
        "ok": True,
        "running": False,
        "workers": 0,
        "queue_size": 0,
        "concurrency": 16,
        "last_heartbeat": now_iso,
    }

    tracker: Dict[str, Any] = await _fetch_tracker_status(detailed=detailed)
    payload: Dict[str, Any] = {**base, **(tracker or {})}

    # Binance env / futures access
    payload.update(_binance_env())
    fa = await _check_futures_access()
    payload.update(fa)

    # normalize times
    lh = _to_iso_from_any(payload.get("last_heartbeat")) or now_iso
    payload["last_heartbeat"] = lh

    started_iso = _to_iso_from_any(payload.get("started_at"))
    if started_iso:
        payload["started_at"] = started_iso
        try:
            if "uptime_sec" not in payload:
                from datetime import datetime as _dt
                sd = _dt.fromisoformat(started_iso.replace("Z", "+00:00"))
                payload["uptime_sec"] = int(max(0, (datetime.now(timezone.utc) - sd.astimezone(timezone.utc)).total_seconds()))
        except Exception:
            pass

    payload.setdefault("workers", 0)
    payload.setdefault("queue_size", 0)
    payload.setdefault("concurrency", 16)
    payload.setdefault("running", bool(payload.get("workers", 0) > 0 or payload.get("queue_size", 0) > 0))
    payload["ok"] = bool(payload.get("ok", True))

    return payload














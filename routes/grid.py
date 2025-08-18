# routes/grid.py
from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

# ---- Auth (Bearer) ---------------------------------------------------------
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:  # pragma: no cover
    def require_bearer_token():
        raise HTTPException(status_code=401, detail="Unauthorized")

# ---- Optional tracker ------------------------------------------------------
try:
    # צפוי להחזיר dict עם מפתחות כמו: ok, running, workers, queue_size, concurrency, last_heartbeat, started_at ...
    from utils.grid_tracker import get_status as _get_status  # type: ignore
    _HAS_TRACKER = True
except Exception:  # pragma: no cover
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
    """
    Try to normalize heartbeat/start times into ISO8601.
    Accepts ISO strings, epoch seconds (int/float), or datetime.
    """
    try:
        if v is None:
            return None
        if isinstance(v, datetime):
            return _iso(v)
        if isinstance(v, (int, float)):
            return _iso(datetime.fromtimestamp(float(v), tz=timezone.utc))
        if isinstance(v, str):
            # assume already ISO-like
            return v
    except Exception:
        return None
    return None


async def _fetch_tracker_status(detailed: bool) -> Dict[str, Any]:
    """
    קרא את ה־tracker אם קיים. תומך גם בפונקציה אסינכרונית וגם בסינכרונית,
    וגם בממשקים שלא מקבלים detailed.
    """
    if not (_HAS_TRACKER and _get_status):
        return {}

    try:
        # נסה להעביר detailed אם הפונקציה מקבלת פרמטר כזה
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

        if isinstance(res, dict):
            return res
        return {}
    except Exception:
        return {}


@router.get(
    "/status",
    summary="Grid status (workers/queue/concurrency)",
    operation_id="getGridStatus",
)
async def grid_status(
    detailed: bool = Query(False, description="Include tracker-specific fields when available."),
) -> Dict[str, Any]:
    """
    מחזיר סטטוס רשת/תור/קונקרנציה. אם קיים utils.grid_tracker – נשתמש בו.
    אחרת מחזירים ערכי ברירת־מחדל בטוחים.
    """
    now_iso = _iso(datetime.now(timezone.utc))

    # בסיס בטוח
    base: Dict[str, Any] = {
        "ok": True,
        "running": False,
        "workers": 0,
        "queue_size": 0,
        "concurrency": 16,
        "last_heartbeat": now_iso,
    }

    # ניסיון לקרוא מה־tracker
    tracker: Dict[str, Any] = await _fetch_tracker_status(detailed=detailed)

    # מיזוג עם הגנות
    payload: Dict[str, Any] = {**base, **(tracker or {})}

    # נרמול זמנים
    lh = _to_iso_from_any(payload.get("last_heartbeat")) or now_iso
    payload["last_heartbeat"] = lh

    started_iso = _to_iso_from_any(payload.get("started_at"))
    if started_iso:
        payload["started_at"] = started_iso
        try:
            # חישוב uptime אם חסר
            if "uptime_sec" not in payload:
                # parse to datetime
                started_dt = datetime.fromisoformat(started_iso.replace("Z", "+00:00"))
                uptime = (datetime.now(timezone.utc) - started_dt.astimezone(timezone.utc)).total_seconds()
                payload["uptime_sec"] = int(max(0, uptime))
        except Exception:
            pass

    # וידוא שדות חובה
    payload.setdefault("workers", 0)
    payload.setdefault("queue_size", 0)
    payload.setdefault("concurrency", 16)
    payload.setdefault("running", bool(payload.get("workers", 0) > 0 or payload.get("queue_size", 0) > 0))

    # דגל הצלחה
    payload["ok"] = bool(payload.get("ok", True))

    return payload













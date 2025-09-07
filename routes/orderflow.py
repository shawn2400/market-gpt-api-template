# routes/orderflow.py
# =========================
# REST API לניתוח Orderflow (CVD, Depth)
# =========================
from __future__ import annotations
import asyncio, time
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, Path, Query, Request, HTTPException
from utils.auth import require_api_key

# אם יש כשל ב-import של החישוב עצמו, נשמר את ה-router טעון ונחזיר שגיאה מבוקרת
try:
    from utils.orderflow import get_orderflow_snapshot
    _OF_OK = True
except Exception as _e:
    get_orderflow_snapshot = None  # type: ignore
    _OF_OK = False
    _OF_ERR = str(_e)

router = APIRouter(
    prefix="",                # אין prefix כדי שהנתיב יהיה בדיוק /orderflow/{symbol}
    tags=["Analytics"],
    dependencies=[Depends(require_api_key)]
)

# --- Rate limit פנימי (קל ופשוט)
_rl_state: Dict[str, List[float]] = {}
def _rl(ip: str | None, limit: int = 15, window: int = 60) -> bool:
    if not ip:
        return True
    now = time.time()
    calls = [c for c in _rl_state.get(ip, []) if now - c < window]
    if len(calls) >= limit:
        return False
    calls.append(now)
    _rl_state[ip] = calls
    return True

# ─────────────────────────────────────────────────────────
# Public ping (לבדיקת רישום הראוטר ב-/openapi.json)
# ─────────────────────────────────────────────────────────
router_public = APIRouter()
@router_public.get("/__of_ping", tags=["Analytics"])
async def orderflow_ping():
    return {"ok": True, "module": "orderflow", "calc_loaded": bool(_OF_OK), "error": (None if _OF_OK else _OF_ERR)}

# ─────────────────────────────────────────────────────────
# עיקר: צילום מצב Orderflow
# שים לב: response_model=None כדי להימנע מבעיות Pydantic עם טיפוסים דינמיים
# ─────────────────────────────────────────────────────────
@router.get("/orderflow/{symbol}", summary="Orderflow snapshot", response_model=None)
async def get_orderflow(
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    trades_limit: int = Query(800, ge=1, le=1000),
    depth_limit: int = Query(500, ge=5, le=1000),
    cvd_window: int = Query(300, ge=1, le=1000),
    request: Request = Path(None, description="Request context (injected by FastAPI)")  # לא Optional, אין =None
) -> Dict[str, Any]:
    # בדיקת קצבים לפי IP
    try:
        ip = request.client.host if request and request.client else None
    except Exception:
        ip = None
    if not _rl(ip):
        raise HTTPException(429, "Rate limit exceeded")

    # אם מודול החישוב לא נטען, נחזיר שגיאה ברורה אבל הראוטר נשאר חי
    if not _OF_OK or not callable(get_orderflow_snapshot):  # type: ignore
        raise HTTPException(500, f"orderflow engine not loaded: {_OF_ERR}")

    # מחשבים ב-thread pool כדי לא לחסום event loop
    return await asyncio.to_thread(
        get_orderflow_snapshot,   # type: ignore
        symbol,
        trades_limit=trades_limit,
        depth_limit=depth_limit,
        cvd_window=cvd_window
    )











  


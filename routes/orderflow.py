# routes/orderflow.py
# =========================
# REST API לניתוח Orderflow (CVD, Depth)
# =========================
from __future__ import annotations
import asyncio, time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, Path, Query, Request, HTTPException
from utils.auth import require_api_key

# נטען את המנוע; אם נופל ב-import, עדיין נטען router_public כדי לראות ב-openapi.json
try:
    from utils.orderflow import get_orderflow_snapshot
    _OF_OK = True
    _OF_ERR: Optional[str] = None
except Exception as _e:
    get_orderflow_snapshot = None  # type: ignore
    _OF_OK = False
    _OF_ERR = str(_e)

# ראוטר מוגן (דורש API key)
router = APIRouter(
    prefix="",
    tags=["Analytics"],
    dependencies=[Depends(require_api_key)]
)

# ראוטר ציבורי קטן כדי לוודא שהמודול נטען ל-OpenAPI גם אם יש כשל פנימי
router_public = APIRouter()

@router_public.get("/__of_ping", tags=["Analytics"])
async def orderflow_ping() -> Dict[str, Any]:
    return {"ok": True, "module": "orderflow", "calc_loaded": bool(_OF_OK), "error": _OF_ERR}

# ---- Rate limit פנימי פשוט ----
_rl_state: Dict[str, List[float]] = {}
def _rl(ip: Optional[str], limit: int = 15, window: int = 60) -> bool:
    if not ip:
        return True
    now = time.time()
    calls = [c for c in _rl_state.get(ip, []) if now - c < window]
    if len(calls) >= limit:
        return False
    calls.append(now)
    _rl_state[ip] = calls
    return True

# ---- Endpoint עיקרי: צילום Orderflow ----
# שים לב: request: Request (ללא Optional/ברירת מחדל) כדי לא להפיל את Pydantic
@router.get("/orderflow/{symbol}", summary="Orderflow snapshot", response_model=None)
async def get_orderflow(
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    trades_limit: int = Query(800, ge=1, le=1000),
    depth_limit: int = Query(500, ge=5, le=1000),
    cvd_window: int = Query(300, ge=1, le=1000),
    request: Request
) -> Dict[str, Any]:
    # Rate-limit לפי IP
    ip = None
    try:
        ip = request.client.host if request and request.client else None
    except Exception:
        ip = None
    if not _rl(ip):
        raise HTTPException(429, "Rate limit exceeded")

    # אם מנוע ה-orderflow לא נטען, מחזירים הודעת שגיאה ברורה
    if not _OF_OK or not callable(get_orderflow_snapshot):  # type: ignore
        raise HTTPException(500, f"orderflow engine not loaded: {_OF_ERR}")

    # חישוב ב-thread מבלי לחסום event loop
    return await asyncio.to_thread(
        get_orderflow_snapshot,  # type: ignore
        symbol,
        trades_limit=trades_limit,
        depth_limit=depth_limit,
        cvd_window=cvd_window
    )












  


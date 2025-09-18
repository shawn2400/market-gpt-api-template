# routes/scan_now_alias.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from typing import Optional

try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

# נרשם גם הוא תחת /scan כדי לא להתנגש עם מודולים אחרים
router = APIRouter(prefix="/scan", tags=["Scanner"], dependencies=[Depends(require_bearer_token)])

# נשתמש בפונקציה מהמודול הראשי אם נטען; אם לא – נזרוק 503 עדין
try:
    from routes.scan_top_volume import scan_top_volume  # type: ignore
except Exception:
    scan_top_volume = None

@router.get("/now", summary="Alias to /scan/top-volume")
async def scan_now(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    symbols: Optional[str] = Query(None, description="CSV e.g. BTCUSDT,ETHUSDT"),
    threshold: float = Query(6.0),
    notify: Optional[str] = Query(None),
    chat_id: Optional[str] = Query(None),
):
    if not scan_top_volume:
        return {"ok": False, "error": "scan_top_volume not available (import failed)", "returned": 0, "count_total": 0}

    symbol = None
    if symbols:
        # אם התקבל CSV ובו סימבול אחד — נעביר אותו כ-symbol
        parts = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if len(parts) == 1:
            symbol = parts[0]

    return await scan_top_volume(
        market=market,
        quote=quote,
        limit=limit,
        timeframe=timeframe,
        kline_limit=kline_limit,
        symbol=symbol,
        threshold=threshold,
        notify=notify,
        chat_id=chat_id,
    )

__all__ = ["router"]

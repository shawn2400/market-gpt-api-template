# routes/scan_now_alias.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from typing import Optional, Dict, Any, List

# auth (fallback בטוח)
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

router = APIRouter(prefix="/scan", tags=["Scanner"], dependencies=[Depends(require_bearer_token)])

# נייבא את המימוש הראשי של הסורק
try:
    from routes.scan_top_volume import scan_top_volume  # type: ignore
except Exception:
    scan_top_volume = None

@router.get("/now", summary="Alias to /scan/top-volume with optional POST-FILTER")
async def scan_now(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    symbols: Optional[str] = Query(None, description="CSV e.g. BTCUSDT,ETHUSDT"),
    # סף ניקוד: תאימות לאחור (אותו שם כמו קודם)
    threshold: Optional[float] = Query(None, description="Minimum score (legacy)"),
    # אלטרנטיבה יותר מפורשת (מפה ל-threshold אם לא סופק):
    min_score: Optional[float] = Query(None, description="Minimum score to keep"),
    # סינון תוצאות ללא צד (side null) כברירת מחדל
    require_side: bool = Query(True, description="Keep only BUY/SELL signals"),
    # פרמטרים של התראה (מועברים למימוש הראשי; כאן אין שליחה נוספת)
    notify: Optional[str] = Query(None, description="telegram / none"),
    chat_id: Optional[str] = Query(None),
    rich: Optional[int] = Query(None, description="1 for rich telegram buttons"),
) -> Dict[str, Any]:
    """
    אליאס ל-/scan/top-volume, עם סינון משלים בצד ה-API:
    - מחזיר רק BUY/SELL אם require_side=true (ברירת מחדל)
    - מסנן לפי ניקוד score>=min_score/threshold אם ניתן
    הערה: ההתראות (notify) מתבצעות במימוש הראשי. האליאס רק מסנן את הפלט החוזר.
    """
    if not scan_top_volume:
        return {"ok": False, "error": "scan_top_volume not available (import failed)", "returned": 0, "count_total": 0, "signals": []}

    # תאימות: אם לא סופק min_score – נשתמש ב-threshold הישן
    if min_score is None and threshold is not None:
        min_score = threshold

    # אם הועברו סמלים — המרה לרשימה ובחירת סימבול יחיד (כמו קודם)
    symbol = None
    if symbols:
        parts = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if len(parts) == 1:
            symbol = parts[0]

    # קריאה למימוש הראשי (שגם יכול לבצע סינונים/התראות משלו)
    base: Dict[str, Any] = await scan_top_volume(
        market=market,
        quote=quote,
        limit=limit,
        timeframe=timeframe,
        kline_limit=kline_limit,
        symbol=symbol,
        threshold=min_score if min_score is not None else (threshold if threshold is not None else 0.0),
        notify=notify,
        chat_id=chat_id,
        rich=rich,
    )

    signals: List[Dict[str, Any]] = list(base.get("signals") or [])
    count_total = int(base.get("count_total") or len(signals))

    # פוסט-פילטר בצד האליאס (שקוף ולא שולח התראות בעצמו)
    filtered: List[Dict[str, Any]] = []
    for s in signals:
        side = (s.get("side") or "").upper()
        score = float(s.get("score") or 0.0)
        if require_side and side not in ("BUY", "SELL"):
            continue
        if min_score is not None and score < float(min_score):
            continue
        filtered.append(s)

    return {
        "ok": True,
        "market": market,
        "quote": quote,
        "mode": base.get("mode") or "compact",
        "count_total": count_total,
        "returned": len(filtered),
        "signals": filtered,
        "applied_filters": {
            "require_side": require_side,
            "min_score": min_score,
        },
        "error": None if base.get("ok") else (base.get("error") or "upstream_error"),
    }

__all__ = ["router"]





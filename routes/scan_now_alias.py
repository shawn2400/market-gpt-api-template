# routes/scan_now_alias.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from typing import Optional, List, Dict, Any

# --- auth (fallback בטוח) ---
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

router = APIRouter(prefix="/scan", tags=["Scanner"], dependencies=[Depends(require_bearer_token)])

# --- נייבא את הסורק הראשי ---
try:
    from routes.scan_top_volume import scan_top_volume  # type: ignore
except Exception:
    scan_top_volume = None


def _passes_side(s: Optional[str]) -> bool:
    return s in ("BUY", "SELL")


def _post_filter(signals: List[Dict[str, Any]],
                 min_score: Optional[float],
                 require_side: bool) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for sig in signals or []:
        score_ok = True if (min_score is None) else (float(sig.get("score") or 0.0) >= float(min_score))
        side_ok = True if not require_side else _passes_side(sig.get("side"))
        if score_ok and side_ok:
            out.append(sig)
    return out


@router.get("/now", summary="Alias to /scan/top-volume (with post-filter + notify-on-filtered)")
async def scan_now(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),

    # תמיכה בסימבול בודד לשמירת תאימות (אם נשלח כאן, נפנה ל-top_volume עם symbol=)
    symbols: Optional[str] = Query(None, description="CSV e.g. BTCUSDT,ETHUSDT"),

    # סף ישן/תואם לאחור (נשמר לתאימות, אבל נעדיף min_score)
    threshold: Optional[float] = Query(None, description="Deprecated alias for min_score"),

    # פרמטרים חדשים לפוסט-פילטר:
    min_score: Optional[float] = Query(None, description="Minimum score after scan"),
    require_side: bool = Query(False, description="If true, require side to be BUY/SELL (exclude null)"),

    # התראות:
    notify: Optional[str] = Query(None, description="telegram | none"),
    chat_id: Optional[str] = Query(None),
    rich: int = Query(0, ge=0, le=1, description="If 1, try to send rich message with buttons"),
):
    """
    שלבי עבודה:
    1) מריצים את scan_top_volume ללא notify כדי לקבל תוצאות גולמיות.
    2) מפעילים פוסט-פילטר (min_score/require_side).
    3) אם יש notify=telegram – שולחים התראות *רק* על המסוננים:
       כדי לעשות reuse ללוגיקת ההתראות שכבר קיימת ב-scan_top_volume,
       נקרא אליו שוב לכל סימבול שעבר פילטר עם symbol=..., notify=telegram.
    """
    if not scan_top_volume:
        return {"ok": False, "error": "scan_top_volume not available (import failed)",
                "returned": 0, "count_total": 0}

    # תאימות: אם לא הועבר min_score אבל הועבר threshold – נשתמש בו:
    if min_score is None and threshold is not None:
        min_score = threshold

    # האם יש סימבול יחיד שנשלח? (לשמירת תאימות)
    single_symbol: Optional[str] = None
    if symbols:
        parts = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if len(parts) == 1:
            single_symbol = parts[0]

    # --- שלב 1: סריקה ללא notify (גולמי) ---
    raw = await scan_top_volume(
        market=market,
        quote=quote,
        limit=limit,
        timeframe=timeframe,
        kline_limit=kline_limit,
        symbol=single_symbol,
        threshold=min_score if min_score is not None else 0.0,  # כדי לא להגביל מוקדם מדי
        notify=None,
        chat_id=None,
        rich=rich,
    )

    # נוודא פורמט צפוי
    ok = bool(raw and isinstance(raw, dict) and raw.get("ok", False))
    signals = (raw.get("signals") if ok else []) or []
    count_total = int(raw.get("count_total") or len(signals))
    mode = raw.get("mode") or "compact"

    # --- שלב 2: פוסט-פילטר ---
    filtered = _post_filter(signals, min_score=min_score, require_side=require_side)

    # --- שלב 3: אם ביקשת התראה – נשלח רק למסוננים ---
    notified = 0
    notify_error: Optional[str] = None
    if notify and notify.lower() == "telegram" and chat_id:
        try:
            # נבצע reuse: לכל סימבול שעבר פילטר – נקרא שוב ל-top_volume
            # עם symbol=<X> ו-notify=telegram (הוא ישלח את ההודעה, כולל rich אם קיים).
            for sig in filtered:
                sym = sig.get("symbol")
                if not sym:
                    continue
                _ = await scan_top_volume(
                    market=market,
                    quote=quote,
                    limit=1,  # לא צריך יותר
                    timeframe=timeframe,
                    kline_limit=kline_limit,
                    symbol=str(sym),
                    threshold=min_score if min_score is not None else 0.0,
                    notify="telegram",
                    chat_id=chat_id,
                    rich=rich,
                )
                notified += 1
        except Exception as e:
            notify_error = str(e)

    # תשובה לקליינט: רק המסוננים
    return {
        "ok": True,
        "count_total": count_total,        # כמה היו גולמיים
        "returned": len(filtered),         # כמה אחרי פילטר
        "signals": filtered,               # רק המסוננים
        "mode": mode,
        "notified": notified,
        "notify_error": notify_error,
        "post_filter": {"min_score": min_score, "require_side": require_side},
    }


__all__ = ["router"]






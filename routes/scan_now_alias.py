# routes/scan_now_alias.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from typing import Optional, Dict, Any

try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

router = APIRouter(prefix="/scan", tags=["Scanner"], dependencies=[Depends(require_bearer_token)])

# נייבא את סורק הטופ-ווליום (מקור האמת)
try:
    from routes.scan_top_volume import scan_top_volume  # type: ignore
except Exception:
    scan_top_volume = None  # type: ignore

# שליחת טלגרם (רשות, לא מפיל אם אין)
_send_telegram = None
try:
    from utils.telegram_notifier import send_text  # type: ignore
    _send_telegram = send_text
except Exception:
    try:
        from utils.telegram_notifier import send_message  # type: ignore
        _send_telegram = send_message
    except Exception:
        _send_telegram = None


def _format_telegram_summary(payload: Dict[str, Any]) -> str:
    """הודעת סיכום קומפקטית לטלגרם עבור תוצאות הסריקה."""
    parts = [f"🔎 Scan results ({payload.get('timeframe','?')}), threshold ≥ {payload.get('threshold')}"]
    signals = payload.get("signals") or []
    if not signals:
        parts.append("— no matches.")
        return "\n".join(parts)

    for s in signals[:15]:
        sym = s.get("symbol")
        side = s.get("side") or "—"
        sc = s.get("score")
        note = s.get("note") or ""
        parts.append(f"• {sym}: {side}  score={sc}  {note}")
    if len(signals) > 15:
        parts.append(f"… +{len(signals)-15} more")

    return "\n".join(parts)


@router.get("/now", summary="Alias to /scan/top-volume (with threshold & optional Telegram notify)")
async def scan_now(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    symbols: Optional[str] = Query(None, description="CSV e.g. BTCUSDT,ETHUSDT"),
    threshold: float = Query(6.0, description="Return only signals with score ≥ threshold"),
    notify: Optional[str] = Query(None, description='e.g. "telegram"'),
    chat_id: Optional[str] = Query(None, description="Telegram chat id"),
) -> Dict[str, Any]:
    """
    אליאס שנשען על /scan/top-volume, מסנן לפי threshold,
    ואם התבקשה התראה לטלגרם — שולח סיכום (אם קיימת פונקציית שליחה במערכת).
    """
    if not scan_top_volume:
        return {
            "ok": False,
            "error": "scan_top_volume not available (import failed)",
            "returned": 0,
            "count_total": 0,
        }

    # אם נשלח CSV יחיד — נוריד אותו ל־symbol יחיד; אם רבים — נעביר בלי פילטור כאן (top-volume כבר בוחר טופ לפי נפח)
    symbol_single: Optional[str] = None
    if symbols:
        parts = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if len(parts) == 1:
            symbol_single = parts[0]

    # שליפת התוצאות המקוריות
    base: Dict[str, Any] = await scan_top_volume(
        market=market,
        quote=quote,
        limit=limit,
        timeframe=timeframe,
        kline_limit=kline_limit,
        symbol=symbol_single,
    )  # type: ignore

    # תקן מבנה ידידותי
    ok = bool(base.get("ok", False))
    items = list(base.get("signals") or [])
    if not ok:
        return {
            "ok": False,
            "error": base.get("error") or "scan_top_volume failed",
            "count_total": base.get("count_total", 0),
            "returned": 0,
            "signals": [],
        }

    # סינון לפי threshold (score ≥ threshold)
    filt = [s for s in items if isinstance(s, dict) and float(s.get("score", 0)) >= float(threshold)]

    out: Dict[str, Any] = {
        "ok": True,
        "market": market,
        "quote": quote,
        "timeframe": timeframe,
        "threshold": threshold,
        "count_total": len(items),
        "returned": len(filt),
        "signals": filt,
        "mode": base.get("mode", "compact"),
    }

    # התראה לטלגרם — אופציונלי, שקט אם אין פונקציה
    if notify and notify.lower() == "telegram":
        note = None
        if not chat_id:
            note = "notify=telegram requested but chat_id is missing"
        elif not _send_telegram:
            note = "notify=telegram requested but no send function available in utils.telegram_notifier"
        else:
            try:
                text = _format_telegram_summary({
                    "timeframe": timeframe,
                    "threshold": threshold,
                    "signals": filt,
                })
                # שליחה (לא זורקת חריגות החוצה)
                _send_telegram(chat_id=chat_id, text=text)  # type: ignore
                out["notified"] = True
                out["notified_count"] = len(filt)
            except Exception as e:
                note = f"telegram send failed: {e}"
        if note:
            out["notified"] = False
            out["notify_note"] = note

    return out


__all__ = ["router"]




# routes/scan_now_alias.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, Request
from typing import Optional, Dict, Any, List
import os

try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

router = APIRouter(prefix="/scan", tags=["Scanner"], dependencies=[Depends(require_bearer_token)])

# --- מקור האמת לסריקה ---
try:
    from routes.scan_top_volume import scan_top_volume  # type: ignore
except Exception:
    scan_top_volume = None  # type: ignore

# --- שליחה לטלגרם: ננסה קודם notifier, ואם אין – API ישיר ---
_send_text = None
_send_message = None
try:
    from utils.telegram_notifier import send_text  # type: ignore
    _send_text = send_text
except Exception:
    pass
try:
    from utils.telegram_notifier import send_message  # type: ignore
    _send_message = send_message
except Exception:
    pass

# נשתמש ב-API ישיר במקרה ואין פונקציות:
_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_TELEGRAM_API = f"https://api.telegram.org/bot{_BOT_TOKEN}" if _BOT_TOKEN else ""


def _format_telegram_summary(payload: Dict[str, Any]) -> str:
    """הודעת טקסט קומפקטית (fallback או הודעה משלימה)."""
    tf = payload.get("timeframe", "?")
    th = payload.get("threshold")
    parts = [f"🔎 Scan results ({tf}), threshold ≥ {th}"]
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


def _build_ops_urls(base_host: str, sig: Dict[str, Any], timeframe: str) -> Dict[str, str]:
    """בונה קישורי /ops/approve|reject ציבוריים (ללא טוקן), עם פרמטרים בסיסיים."""
    from urllib.parse import urlencode
    q = {
        "symbol": sig.get("symbol"),
        "side": sig.get("side"),
        "tf": timeframe,
        "score": sig.get("score"),
        "src": "scan",
    }
    qs = urlencode(q, doseq=False, safe=",:")
    approve = f"{base_host.rstrip('/')}/ops/approve?{qs}"
    reject = f"{base_host.rstrip('/')}/ops/reject?{qs}"
    return {"approve": approve, "reject": reject}


def _binance_chart_url(symbol: str, market: str, timeframe: str) -> str:
    """קישור מהיר לגרף בבייננס (פיצ'רס/ספוט)."""
    sym = (symbol or "BTCUSDT").upper()
    if (market or "futures").lower().startswith("future"):
        # Binance Futures chart
        return f"https://www.binance.com/en/futures/{sym}?interval={timeframe}"
    # Spot chart
    return f"https://www.binance.com/en/trade/{sym}?type=spot&interval={timeframe}"


async def _telegram_send_with_buttons(chat_id: str, text: str, buttons: List[List[Dict[str, str]]]) -> bool:
    """
    שולח הודעה עם inline keyboard.
    1) אם יש utils.telegram_notifier.send_message(text=..., reply_markup=...), נשתמש בה.
    2) אחרת נשתמש ב-HTTP ישיר ל-telegram sendMessage.
    """
    # ניסיון 1: notifier פנימי (אם קיים ותומך ב-reply_markup)
    if _send_message:
        try:
            _send_message(chat_id=chat_id, text=text, reply_markup={"inline_keyboard": buttons})  # type: ignore
            return True
        except Exception:
            pass

    # ניסיון 2: API ישיר
    if not _TELEGRAM_API:
        return False

    try:
        import httpx  # שימוש לוקאלי (יש לך כבר httpx בתכנה)
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": buttons},
            "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(f"{_TELEGRAM_API}/sendMessage", json=payload)
            return bool(r.status_code == 200 and r.json().get("ok"))
    except Exception:
        return False


async def _telegram_send_text(chat_id: str, text: str) -> bool:
    """שליחת טקסט רגיל בלבד (fallback)."""
    # ניסיון 1: notifier פנימי send_text
    if _send_text:
        try:
            _send_text(chat_id=chat_id, text=text)  # type: ignore
            return True
        except Exception:
            pass

    # ניסיון 2: notifier פנימי send_message ללא כפתורים
    if _send_message:
        try:
            _send_message(chat_id=chat_id, text=text)  # type: ignore
            return True
        except Exception:
            pass

    # ניסיון 3: API ישיר
    if not _TELEGRAM_API:
        return False

    try:
        import httpx
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(f"{_TELEGRAM_API}/sendMessage", json=payload)
            return bool(r.status_code == 200 and r.json().get("ok"))
    except Exception:
        return False


@router.get("/now", summary="Alias to /scan/top-volume (with threshold & optional rich Telegram notify)")
async def scan_now(
    request: Request,
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    symbols: Optional[str] = Query(None, description="CSV e.g. BTCUSDT,ETHUSDT"),
    threshold: float = Query(6.0, description="Return only signals with score ≥ threshold"),
    notify: Optional[str] = Query(None, description='e.g. "telegram"'),
    chat_id: Optional[str] = Query(None, description="Telegram chat id"),
    rich: bool = Query(False, description="Send rich Telegram message with inline buttons if notify=telegram"),
) -> Dict[str, Any]:
    """
    אליאס ל-/scan/top-volume:
    - מסנן לפי threshold
    - אופציונלית שולח לטלגרם טקסט או הודעה עשירה (inline buttons לאישור/דחייה).

    כפתורים מכוונים ל-/ops/approve ו-/ops/reject, שהם נתיבים ציבוריים לפי ההגדרות ב-main.py.
    """
    if not scan_top_volume:
        return {
            "ok": False,
            "error": "scan_top_volume not available (import failed)",
            "returned": 0,
            "count_total": 0,
        }

    # parse CSV לסימבול יחיד (אם רק אחד)
    symbol_single: Optional[str] = None
    if symbols:
        parts = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if len(parts) == 1:
            symbol_single = parts[0]

    # בקשת הבסיס
    base: Dict[str, Any] = await scan_top_volume(
        market=market,
        quote=quote,
        limit=limit,
        timeframe=timeframe,
        kline_limit=kline_limit,
        symbol=symbol_single,
    )  # type: ignore

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

    # סינון סף
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

    # --- התראה לטלגרם ---
    if notify and notify.lower() == "telegram":
        note = None
        sent = False

        if not chat_id:
            note = "notify=telegram requested but chat_id is missing"
        else:
            # נקבע base_host חיצוני (PUBLIC_HOST) או לפי הבקשה
            base_host = os.getenv("PUBLIC_HOST", "").strip()
            if not base_host:
                base_host = str(request.base_url).rstrip("/")

            if rich:
                # מגבלה ל-8 כפתורים (המשתמש ביקש 4–8 בו-זמנית)
                top = filt[:8] if len(filt) > 8 else filt
                if not top:
                    # אם אין סיגנלים – נשלח טקסט מינימלי
                    msg = _format_telegram_summary({"timeframe": timeframe, "threshold": threshold, "signals": []})
                    sent = await _telegram_send_text(chat_id=chat_id, text=msg)
                else:
                    # נבנה מקבץ כפתורים: לכל סימבול – 2 כפתורים (Approve / Reject) + שורת קישור לגרף
                    buttons: List[List[Dict[str, str]]] = []
                    for sig in top:
                        urls = _build_ops_urls(base_host, sig, timeframe)
                        sym = sig.get("symbol")
                        side = sig.get("side")
                        chart = _binance_chart_url(sym, market, timeframe)

                        buttons.append([
                            {"text": f"✅ Approve {sym} {side}", "url": urls["approve"]},
                            {"text": f"⛔ Reject", "url": urls["reject"]},
                        ])
                        buttons.append([
                            {"text": f"📈 Chart {sym}", "url": chart}
                        ])

                    header = f"🔎 *Scan {timeframe}* (≥ {threshold}) — {len(top)}/{len(filt)} signals"
                    sent = await _telegram_send_with_buttons(chat_id=chat_id, text=header, buttons=buttons)

                    # אם שליחת כפתורים נכשלה — נשלח טקסט רגיל כסיכום
                    if not sent:
                        msg = _format_telegram_summary({"timeframe": timeframe, "threshold": threshold, "signals": top})
                        sent = await _telegram_send_text(chat_id=chat_id, text=msg)
            else:
                # לא rich — טקסט בלבד
                msg = _format_telegram_summary({"timeframe": timeframe, "threshold": threshold, "signals": filt})
                sent = await _telegram_send_text(chat_id=chat_id, text=msg)

        out["notified"] = bool(sent)
        if note:
            out["notify_note"] = note

    return out


__all__ = ["router"]





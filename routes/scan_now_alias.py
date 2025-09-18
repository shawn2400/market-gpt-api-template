# routes/scan_now_alias.py
from __future__ import annotations
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query
import os
import httpx

# --- auth dependency (fallback safe) ---
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

router = APIRouter(prefix="/scan", tags=["Scanner"], dependencies=[Depends(require_bearer_token)])

# --- import the compact scanner (we reuse its logic & models) ---
ScanResponse = Dict[str, Any]  # אם המודלים לא זמינים, נישאר טייפ גנרי
try:
    from routes.scan_top_volume import scan_top_volume  # type: ignore
except Exception:
    scan_top_volume = None  # type: ignore

# ---------- helpers ----------

async def _notify_telegram(chat_id: str, text: str) -> bool:
    """
    שולח התראה לטלגרם ישירות דרך ה-API הרשמי, אם יש BOT_TOKEN בסביבה.
    מחזיר True אם הצליח, אחרת False (ללא חריגה כלפי חוץ).
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token or not chat_id:
        return False
    api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(api, json=payload)
            r.raise_for_status()
        return True
    except Exception:
        return False


def _format_signal_line(sig: Dict[str, Any]) -> str:
    sym = sig.get("symbol")
    tf = sig.get("timeframe")
    side = sig.get("side") or "-"
    score = sig.get("score")
    det = sig.get("details") or {}
    adx = det.get("adx")
    rsi = det.get("rsi")
    trend = det.get("trend", "")
    return f"• {sym} [{tf}] {side} | score={score} | ADX={adx} | RSI={rsi} | trend={trend}"


def _filter_by_threshold(resp: Dict[str, Any], thr: float) -> Dict[str, Any]:
    """
    מקבל את תשובת scan_top_volume (מילון), מחזיר תשובה זהה בתצורה
    אך עם signals מסוננים לפי score>=thr, ומוסיף שדות עזר.
    """
    out = dict(resp or {})
    sigs: List[Dict[str, Any]] = list(out.get("signals") or [])
    kept = [s for s in sigs if (s.get("score") is not None and float(s.get("score")) >= float(thr))]
    out["signals"] = kept
    out["returned"] = len(kept)
    out["count_total"] = len(sigs)
    out["threshold_used"] = thr
    out["filtered"] = True
    return out


# ---------- endpoint (alias) ----------

@router.get("/now", summary="Alias to /scan/top-volume with threshold & optional Telegram notify")
async def scan_now(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    symbols: Optional[str] = Query(None, description="CSV e.g. BTCUSDT,ETHUSDT"),
    threshold: float = Query(6.0, description="סינון לפי score>=threshold"),
    notify: Optional[str] = Query(None, description="אם='telegram' תשלח התראה על ה־signals המסוננים"),
    chat_id: Optional[str] = Query(None, description="נדרש כאשר notify=telegram"),
) -> ScanResponse:
    """
    אליאס ידידותי לתאימות אחורה:
    - מפעיל את /scan/top-volume
    - מסנן לפי threshold (score>=threshold)
    - אם notify=telegram ויש chat_id => ישלח סיכום לטלגרם (Best-Effort)
    - תומך בפרמטר 'symbols' (CSV) - אם יש סימבול אחד, נריץ פילטר יחיד מול הסורק
    """
    if not scan_top_volume:
        return {
            "ok": False,
            "error": "scan_top_volume not available (import failed)",
            "returned": 0,
            "count_total": 0,
            "signals": [],
        }

    # תמיכת תאימות: אם הגיע CSV ובו סימבול אחד — נבצע פילטר נקודתי בסורק הראשי
    symbol = None
    if symbols:
        parts = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if len(parts) == 1:
            symbol = parts[0]

    # קריאה לסורק הראשי (לא מעבירים לו notify/threshold כדי לא לשבור חתימה)
    base_resp: Dict[str, Any] = await scan_top_volume(
        market=market,
        quote=quote,
        limit=limit,
        timeframe=timeframe,
        kline_limit=kline_limit,
        symbol=symbol,
    )

    if not (base_resp or {}).get("ok", False):
        # העברנו הלאה את השגיאה כמו שהיא
        return base_resp

    # סינון לפי threshold
    filtered = _filter_by_threshold(base_resp, threshold)

    # התראה לטלגרם (Best-Effort)
    notified = False
    notified_count = 0
    if (notify or "").lower() == "telegram" and chat_id and filtered.get("signals"):
        lines = [_format_signal_line(s) for s in filtered["signals"]]
        hdr = "🔔 *Scan Now* — Top matches (score ≥ {:.2f}):".format(float(threshold))
        # בלי Markdown כדי לא להסתבך בפורמט; טקסט פשוט:
        msg = hdr + "\n" + "\n".join(lines[:20])  # חותך ל-20 שורות ליתר בטחון
        notified = await _notify_telegram(chat_id, msg)
        notified_count = len(filtered["signals"])

    # שדות עזר למי שקורא דרך האליאס
    filtered["alias"] = "scan/now"
    filtered["notify"] = notify
    filtered["chat_id"] = chat_id
    filtered["notified"] = bool(notified)
    filtered["notified_count"] = int(notified_count)

    return filtered


__all__ = ["router"]



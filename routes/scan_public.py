# routes/scan_public.py
from __future__ import annotations

from typing import Any, Dict, List, Iterable, Tuple
from fastapi import APIRouter, Query
from contextlib import suppress
import inspect

router = APIRouter(prefix="/scan", tags=["scan"])

# ננסה למחזר את חישוב הסיגנלים הפנימי
_compute_signals = None
with suppress(Exception):
    from routes.scan_top_volume import _compute_signals  # type: ignore


def _project_public(sig: Dict[str, Any]) -> Dict[str, Any]:
    """
    הקרנה לשדות ציבוריים בלבד. לא מחזירים מזהים/כמויות/תקציבים/כתובות/לינקים וכו'.
    """
    details = sig.get("details") or {}
    return {
        "symbol": str(sig.get("symbol") or "").upper(),
        "timeframe": str(sig.get("timeframe") or ""),
        "side": (str(sig.get("side") or "").upper() or None),
        "score": float(sig.get("score")) if sig.get("score") is not None else None,
        "note": sig.get("note"),
        # אינדיקטיבים בלבד — בלי פרטי הזמנה
        "trend": details.get("trend"),
        "rsi": details.get("rsi"),
        "ema21": details.get("ema21"),
        "ema50": details.get("ema50"),
    }


async def _maybe_await(fn, *args, **kwargs):
    """
    מאפשר קריאה גם אם _compute_signals מוגדרת כ-sync וגם אם היא async.
    """
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    res = fn(*args, **kwargs)
    if inspect.isawaitable(res):
        return await res
    return res


def _coerce_seq(obj: Any) -> List[Dict[str, Any]]:
    """
    דואג שלבסוף תהיה רשימת סיגנלים (dict). אם מגיע tuple (signals, meta) נחלץ את הראשון.
    """
    if isinstance(obj, tuple) and obj:
        obj = obj[0]
    if obj is None:
        return []
    if isinstance(obj, Iterable) and not isinstance(obj, (dict, str, bytes)):
        return [x for x in obj]  # type: ignore
    return []


@router.get("/public-now", summary="Public scan (read-only, no approvals/alerts)")
async def scan_public_now(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    min_score: float = Query(7.0),
    require_side: bool = Query(True),
):
    """
    סריקה ציבורית לקריאה בלבד: לא מבצעת אישורים/התראות.
    מחזירה רק שדות אינדיקטיביים.
    """
    if _compute_signals is None:
        return {"ok": False, "error": "scanner_unavailable", "signals": [], "mode": "public"}

    try:
        raw = await _maybe_await(_compute_signals, market, quote, limit, timeframe, kline_limit)
        signals_in: List[Dict[str, Any]] = _coerce_seq(raw)

        filtered = []
        for s in signals_in:
            try:
                score_val = float(s.get("score") or 0)
            except Exception:
                score_val = 0.0
            side_val = str(s.get("side") or "").upper()

            if score_val < float(min_score or 0):
                continue
            if require_side and side_val not in ("BUY", "SELL"):
                continue

            filtered.append(_project_public(s))

        return {
            "ok": True,
            "returned": len(filtered),
            "signals": filtered,
            "mode": "public"
        }

    except Exception as e:
        # לא חושפים traceback — רק הודעת שגיאה כללית
        return {
            "ok": False,
            "error": f"public_scan_failed: {e}",
            "signals": [],
            "mode": "public"
        }

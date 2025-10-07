# routes/scan_public.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query
from .scan_top_volume import _compute_signals  # מייבא את החישוב הקיים (RSI/EMA וכו')

router = APIRouter(prefix="/scan", tags=["Scanner"])

def _project_public(sig: Dict[str, Any]) -> Dict[str, Any]:
    d = sig.get("details") or {}
    return {
        "symbol": str(sig.get("symbol") or "").upper(),
        "timeframe": str(sig.get("timeframe") or ""),
        "side": sig.get("side"),
        "score": sig.get("score"),
        "note": sig.get("note"),
        "trend": d.get("trend"),
        "rsi": d.get("rsi"),
        "ema21": d.get("ema21"),
        "ema50": d.get("ema50"),
        # ללא close/entry_price/ttl או כל דבר שקשור לאישור/הזמנה
    }

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
    try:
        raw = await _compute_signals(market, quote, limit, timeframe, kline_limit)
        filtered = [
            _project_public(s) for s in (raw or [])
            if isinstance(s, dict)
            and float(s.get("score") or 0) >= float(min_score or 0)
            and (not require_side or (str(s.get("side") or "").upper() in ("BUY","SELL")))
        ]
        return {"ok": True, "returned": len(filtered), "signals": filtered, "mode": "public"}
    except Exception as e:
        return {"ok": False, "error": f"public_scan_failed: {e}", "signals": [], "mode": "public"}

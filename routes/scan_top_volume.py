# routes/scan_top_volume.py
from __future__ import annotations

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Query, Depends

# אימות לנתיבים המורחבים; את /symbols/top-volume נשאיר פתוח
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

router = APIRouter(tags=["Scan"], dependencies=[Depends(require_bearer_token)])
router_symbols = APIRouter(tags=["Analytics"])  # פתוח לקריאה

# --- lite source (תמיד זמין) ---
def _top_symbols(market: str, quote: str, limit: int, min_qv: float) -> List[str]:
    try:
        from utils.top_volume import get_top_volume_symbols  # type: ignore
        ok, syms = get_top_volume_symbols(market=market, quote=quote, limit=limit, min_quote_volume=min_qv)
        return syms if ok else []
    except Exception:
        return []

@router_symbols.get("/symbols/top-volume", operation_id="getTopVolumeSymbols")
def get_top_volume_symbols_endpoint(
    market: str = Query("futures", pattern="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    min_quote_volume: float = Query(0.0, ge=0.0),
):
    syms = _top_symbols(market, quote, limit, min_quote_volume)
    return {"ok": True, "market": market, "quote": quote, "limit": limit, "symbols": syms}

@router.get("/scan/top-volume", operation_id="getScanTopVolume")
async def scan_top_volume(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    trending_only: bool = Query(False),
    mode: str = Query("lite", pattern="^(lite|auto)$"),
):
    """
    mode=lite → רק רשימת סמלים לפי נפח (מהיר, תמיד 200).
    mode=auto → ניסיון לסריקה מלאה (עם נפילות-חסינות → fallback ל-lite).
    """
    symbols = _top_symbols(market, quote, limit, 0.0)
    if not symbols:
        return {"ok": True, "count": 0, "signals": [], "note": "no symbols (top-volume empty)"}

    if mode == "lite":
        # מחזיר “סיגנלים ריקים” — רק תעלות בדיקות/תזמונים
        sigs = [{"symbol": s, "timeframe": timeframe, "side": None, "score": None, "note": "lite"} for s in symbols]
        return {"ok": True, "count": len(sigs), "signals": sigs}

    # mode=auto → ננסה סריקה מלאה — ואם נכשל, ניפול ללייט
    try:
        from utils.multi_tf_scanner import multi_tf_scan_with_ai  # type: ignore
        results: List[Dict[str, Any]] = await multi_tf_scan_with_ai(
            timeframes=(timeframe, "1h"),
            markets=(market,),
            min_quality=6.0,
            top=min(30, limit),
            trending_only=trending_only,
            trending_source="binance24h",
        )
        signals = []
        for r in results or []:
            signals.append({
                "symbol": r.get("symbol"),
                "timeframe": timeframe,
                "side": r.get("signal"),
                "score": r.get("quality_score"),
                "note": r.get("reason"),
                "details": r.get("details"),
            })
        return {"ok": True, "count": len(signals), "signals": signals}
    except Exception as e:
        # fallback → lite
        sigs = [{"symbol": s, "timeframe": timeframe, "side": None, "score": None, "note": f"fallback-lite: {type(e).__name__}"} for s in symbols]
        return {"ok": True, "count": len(sigs), "signals": sigs, "fallback": True}






















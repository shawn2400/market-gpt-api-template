# routes/scan_top_volume.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Query, Depends

try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

router = APIRouter(tags=["Scan"], dependencies=[Depends(require_bearer_token)])
router_symbols = APIRouter(tags=["Analytics"], dependencies=[Depends(require_bearer_token)])

@router_symbols.get("/symbols/top-volume", operation_id="getTopVolumeSymbols")
def top_volume_symbols(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    min_quote_volume: float = Query(0.0),
) -> Dict[str, Any]:
    from utils.top_volume import get_top_volume_symbols
    ok, syms = get_top_volume_symbols(market=market, quote=quote, limit=limit, min_quote_volume=min_quote_volume)
    return {"ok": ok, "market": market, "quote": quote, "limit": limit, "symbols": syms}

@router.get("/scan/top-volume", operation_id="getScanTopVolume")
async def scan_top_volume(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    trending_only: bool = Query(False),
    concurrency: int = Query(16, ge=2, le=64),
) -> Dict[str, Any]:
    from utils.top_volume import get_top_volume_symbols
    ok, syms = get_top_volume_symbols(market=market, quote=quote, limit=limit, min_quote_volume=0.0)

    signals: List[Dict[str, Any]] = []
    note_fallback: Optional[str] = None

    try:
        from utils.multi_tf_scanner import multi_tf_scan_with_ai  # type: ignore
        items = await multi_tf_scan_with_ai(
            timeframes=(timeframe, "1h"),
            markets=(market,),
            min_quality=0.0,
            top=len(syms) or limit,
            trending_only=trending_only,
            trending_source="binance24h",
            symbols=syms or None,
            concurrency=concurrency,
        )
        for it in items or []:
            signals.append({
                "symbol": it.get("symbol"),
                "timeframe": timeframe,
                "side": {"BUY": "LONG", "SELL": "SHORT"}.get(str(it.get("signal","HOLD")).upper(), None),
                "score": float(it.get("quality_score") or 0.0),
                "note": it.get("reason") or None,
                "details": it.get("details") or None,
            })
    except Exception as e:
        note_fallback = f"lite (scanner-fallback: {type(e).__name__})"
        for s in syms:
            signals.append({"symbol": s, "timeframe": timeframe, "side": None, "score": 0.0, "note": "lite", "details": None})

    return {"ok": True, "count": len(signals), "signals": signals, "fallback": note_fallback}

























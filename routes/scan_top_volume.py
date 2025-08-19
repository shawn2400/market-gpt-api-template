# routes/scan_top_volume.py
from __future__ import annotations
import asyncio
from typing import List, Dict, Any, Literal
from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi import Request

# ----- Auth safe-wrapper -----
try:
    from utils.auth import require_bearer_token as _raw_require_bearer  # type: ignore
    from fastapi import HTTPException as _HTTPExc
    def require_bearer_token():
        try:
            return _raw_require_bearer()
        except _HTTPExc:
            raise
        except Exception as e:
            # אל תתרסק על באג פנימי באימות → 401 נקי
            raise HTTPException(status_code=401, detail="Unauthorized") from e
except Exception:
    def require_bearer_token():
        return None

from utils.top_volume import get_top_volume_symbols

router = APIRouter(
    prefix="/scan",
    tags=["Scan"],
    dependencies=[Depends(require_bearer_token)],
)
router_symbols = APIRouter(
    prefix="/symbols",
    tags=["Analytics"],
    dependencies=[Depends(require_bearer_token)],
)

async def _signal_lite(symbol: str, timeframe: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "side": None,
        "score": 0.0,
        "note": None,
        "details": None,
    }

async def _signal_auto(symbol: str, timeframe: str) -> Dict[str, Any]:
    try:
        from utils.multi_tf_scanner import analyze_symbol  # type: ignore
        res = await analyze_symbol(symbol=symbol, interval=timeframe, market_type="futures", bars=200)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "side": (res or {}).get("direction"),
            "score": float((res or {}).get("quality_score", 0) or 0.0),
            "note": (res or {}).get("reason"),
            "details": {
                "rsi": (res or {}).get("rsi"),
                "adx": (res or {}).get("adx"),
                "atr": (res or {}).get("atr"),
                "trend": (res or {}).get("trend"),
                "signal": (res or {}).get("signal"),
            } if isinstance(res, dict) else None,
        }
    except Exception as e:
        # אל תיפול — חזור ל-lite עם הערה
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "side": None,
            "score": 0.0,
            "note": f"auto-fallback: {type(e).__name__}",
            "details": None,
        }

@router.get("/top-volume", operation_id="getScanTopVolume")
async def get_scan_top_volume(
    request: Request,
    market: str = Query("futures", pattern="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    mode: Literal["lite", "auto", "deep"] = Query("lite"),
    concurrency: int = Query(16, ge=2, le=64),
):
    """
    mode=lite (ברירת מחדל) → תמיד יציב.
    mode=auto → ננסה סורק אם קיים; אחרת fallback ל-lite.
    mode=deep → מחייב מודול סורק; אם חסר → 503.
    """
    ok, symbols = get_top_volume_symbols(market=market, quote=quote, limit=limit)
    if not ok:
        # 502 במקום 500
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch top-volume symbols")

    sem = asyncio.Semaphore(concurrency)

    async def _work(sym: str):
        async with sem:
            if mode == "lite":
                return await _signal_lite(sym, timeframe)
            if mode == "auto":
                return await _signal_auto(sym, timeframe)
            # deep → מחייב סורק; אם אין — 503, לא 500
            try:
                from utils.multi_tf_scanner import analyze_symbol  # type: ignore
            except Exception:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="deep mode requires scanner")
            res = await analyze_symbol(symbol=sym, interval=timeframe, market_type="futures", bars=200)
            return {
                "symbol": sym,
                "timeframe": timeframe,
                "side": (res or {}).get("direction"),
                "score": float((res or {}).get("quality_score", 0) or 0.0),
                "note": (res or {}).get("reason"),
                "details": res if isinstance(res, dict) else None,
            }

    # חשוב: לא לאפשר חריגה מכל טסק להפוך ל-500
    tasks = [asyncio.create_task(_work(s)) for s in symbols]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    signals: List[Dict[str, Any]] = []
    errors: List[str] = []

    for item in gathered:
        if isinstance(item, Exception):
            errors.append(f"{type(item).__name__}: {item}")
            continue
        signals.append(item)

    return {
        "ok": True,
        "count": len(signals),
        "signals": signals,
        "errors": errors or None,
        "mode": mode,
        "market": market,
        "quote": quote,
    }

@router_symbols.get("/top-volume", operation_id="getTopVolumeSymbols")
def get_top_volume_symbols_endpoint(
    market: str = Query("futures", pattern="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=500),
    min_quote_volume: float = Query(0.0, ge=0.0),
):
    ok, symbols = get_top_volume_symbols(
        market=market, quote=quote, limit=limit, min_quote_volume=min_quote_volume
    )
    return {"ok": ok, "market": market, "quote": quote, "limit": limit, "symbols": symbols}
















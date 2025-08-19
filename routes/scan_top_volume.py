# routes/scan_top_volume.py
from __future__ import annotations
import asyncio
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Query

try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

from utils.top_volume import get_top_volume_symbols
from routes.ai_analyze import _fetch_klines, _frame_to_df, _analyze

router_symbols = APIRouter(tags=["Analytics"])                           # פתוח
router = APIRouter(tags=["Scan"], dependencies=[Depends(require_bearer_token)])  # מוגן

@router_symbols.get("/symbols/top-volume", operation_id="getTopVolumeSymbols")
async def symbols_top_volume(
    market: str = Query("futures", pattern="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    min_quote_volume: float = Query(0.0)
):
    ok, symbols = get_top_volume_symbols(market=market, quote=quote, limit=limit, min_quote_volume=min_quote_volume)
    return {"ok": ok, "market": market, "quote": quote, "limit": limit, "symbols": symbols}

async def _scan_symbol(symbol: str, timeframe: str, bars: int) -> Dict[str, Any]:
    try:
        rows = await _fetch_klines(symbol, interval=timeframe, limit=bars)
        df = _frame_to_df(rows)
        if len(df) < 60:
            return {"symbol": symbol, "timeframe": timeframe, "side": None, "score": 0.0, "note": "lite (not enough data)", "details": None}
        res = _analyze(df)
        side = {"BUY":"LONG", "SELL":"SHORT", "HOLD":None}.get(res["signal"])
        return {
            "symbol": symbol, "timeframe": timeframe, "side": side,
            "score": float(res["quality_score"] or 0.0) if res.get("quality_score") is not None else 0.0,
            "note": res.get("reason"),
            "details": {
                "rsi": res.get("rsi"), "adx": res.get("adx"), "atr": res.get("atr"),
                "trend": res.get("trend"), "close": res.get("close"),
            }
        }
    except Exception as e:
        return {"symbol": symbol, "timeframe": timeframe, "side": None, "score": 0.0, "note": f"lite ({type(e).__name__})", "details": None}

@router.get("/scan/top-volume", operation_id="getScanTopVolume")
async def scan_top_volume(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    bars: int = Query(200, ge=50, le=1500),
    trending_only: bool = Query(False),
    concurrency: int = Query(12, ge=2, le=64),
    mode: str = Query("lite", description="lite|auto – lite תמיד יחזיר 200")
):
    ok, symbols = get_top_volume_symbols(market=market, quote=quote, limit=limit)
    if not ok or not symbols:
        return {"ok": False, "count": 0, "signals": []}

    use_symbols = symbols if not trending_only else [s for i, s in enumerate(symbols) if i < max(5, limit // 2)]
    sem = asyncio.Semaphore(concurrency)

    async def _task(sym: str):
        async with sem:
            return await _scan_symbol(sym, timeframe, bars)

    results = await asyncio.gather(*[_task(s) for s in use_symbols], return_exceptions=False)
    return {"ok": True, "count": len(results), "signals": results}























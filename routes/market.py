# routes/market.py
from __future__ import annotations
from typing import Dict, Any
from fastapi import APIRouter, Depends, Query

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

from utils.top_volume import get_top_volume_symbols

router = APIRouter(prefix="/symbols", tags=["Analytics"], dependencies=[Depends(require_bearer_token)])

@router.get("/top-volume", summary="Top symbols by volume (Binance)", operation_id="getTopVolumeSymbols")
async def get_top_volume(
    market: str = Query("futures", enum=["futures","spot"]),
    quote:  str = Query("USDT"),
    limit:  int = Query(50, ge=1, le=200),
    min_quote_volume: float = Query(0.0, ge=0.0),
) -> Dict[str, Any]:
    import asyncio
    ok, symbols = await asyncio.to_thread(get_top_volume_symbols, market, quote, limit, min_quote_volume)
    return {"ok": bool(ok), "market": market, "quote": quote, "limit": limit, "symbols": symbols or []}




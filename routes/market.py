from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from utils.auth import require_api_key
from utils.binance_client import get_cached_symbol_info

router = APIRouter(dependencies=[Depends(require_api_key)])

@router.get("/symbol-info")
def market_symbol_info(symbol: str = Query(..., min_length=6, max_length=20), force_refresh: bool = False):
    info_map = get_cached_symbol_info(force_refresh=force_refresh)
    d = info_map.get(symbol.upper())
    if not d:
        raise HTTPException(status_code=404, detail="symbol info unavailable")
    return {"symbol": symbol.upper(), **d}










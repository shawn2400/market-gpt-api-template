# routes/market.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from utils.auth import require_api_key
from utils.binance_client import get_symbol_info, futures_mark_price

router = APIRouter(prefix="/market", dependencies=[Depends(require_api_key)], tags=["Market"])

@router.get("/symbol-info")
def symbol_info(symbol: str = Query(..., min_length=6, max_length=20), force_refresh: int = 0):
    info = get_symbol_info(symbol, force_refresh=bool(force_refresh))
    if not info:
        raise HTTPException(status_code=404, detail="symbol not found or unavailable")
    return info

@router.get("/tickers")
def tickers(symbols: str = Query(..., description="Comma-separated, e.g. BTCUSDT,ETHUSDT")):
    out = {}
    for raw in symbols.split(","):
        sym = raw.strip().upper()
        if not sym:
            continue
        out[sym] = futures_mark_price(sym)
    return out















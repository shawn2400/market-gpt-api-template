# routes/market.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from utils.auth import require_api_key
from utils.binance_client import get_symbol_info, futures_mark_price

router = APIRouter(dependencies=[Depends(require_api_key)], tags=["Market"])

@router.get("/symbol-info")
def symbol_info(
    symbol: str = Query(..., min_length=6, max_length=20),
    force_refresh: int = Query(0, description="1=ריענון exchangeInfo לפני החיפוש"),
):
    info = get_symbol_info(symbol, force_refresh=bool(force_refresh))
    if not info:
        raise HTTPException(status_code=404, detail="Symbol not found or exchangeInfo unavailable")
    return info

@router.get("/tickers")
def tickers(symbols: str = Query(..., description="CSV e.g. BTCUSDT,ETHUSDT,BNBUSDT")):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not syms:
        raise HTTPException(status_code=400, detail="No symbols provided")
    out = {}
    for s in syms:
        out[s] = futures_mark_price(s)
    return out














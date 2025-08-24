# routes/market.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from utils.auth import require_api_key
from utils.binance_client import get_cached_symbol_info, futures_mark_price, valid_futures_symbols

router = APIRouter(prefix="/market", dependencies=[Depends(require_api_key)])

@router.get("/symbol-info")
def symbol_info(
    symbol: str = Query(..., min_length=6, max_length=20),
    force_refresh: int = Query(0, ge=0, le=1),
):
    info = get_cached_symbol_info(symbol, force_refresh=bool(force_refresh))
    if not info:
        raise HTTPException(status_code=404, detail="symbol not found")
    return info

@router.get("/tickers")
def tickers(symbols: str | None = Query(None, description="comma-separated e.g. BTCUSDT,ETHUSDT")):
    out = {}
    if symbols:
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        syms = list(valid_futures_symbols())[:20]
    if not syms:
        raise HTTPException(status_code=400, detail="no symbols to fetch")
    for s in syms:
        out[s] = futures_mark_price(s)
    return out














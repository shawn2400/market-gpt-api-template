from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from utils.auth import require_api_key
from utils.binance_client import (
    status_snapshot,
    futures_mark_price,
    get_cached_symbol_info,
)

router = APIRouter(dependencies=[Depends(require_api_key)])

@router.get("/status")
def binance_status():
    snap = status_snapshot()
    samples = {}
    errors = {}
    for sym in ("BTCUSDT", "ETHUSDT", "BNBUSDT"):
        try:
            samples[sym] = futures_mark_price(sym)
        except Exception as e:
            samples[sym] = None
            errors[sym] = str(e)
    snap["samples"] = samples
    if errors:
        snap["sample_errors"] = errors
    return snap

@router.get("/mark-price")
def mark_price(symbol: str = Query(..., min_length=6, max_length=20)):
    price = futures_mark_price(symbol)
    if price is None:
        raise HTTPException(status_code=503, detail="mark price unavailable")
    return {"symbol": symbol.upper(), "markPrice": price}

@router.get("/symbol-info")
def symbol_info(symbol: str = Query(..., min_length=6, max_length=20), force_refresh: bool = False):
    info_map = get_cached_symbol_info(force_refresh=force_refresh)
    d = info_map.get(symbol.upper())
    if not d:
        raise HTTPException(status_code=404, detail="symbol info unavailable")
    return {"symbol": symbol.upper(), **d}

@router.get("/ping")
def ping():
    return {"ok": True}




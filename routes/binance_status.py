# routes/binance_status.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from utils.auth import require_api_key
from utils.binance_client import status_snapshot, futures_mark_price, fapi_ping

router = APIRouter(prefix="/binance", dependencies=[Depends(require_api_key)], tags=["Binance"])

@router.get("/ping")
def binance_ping():
    ok = fapi_ping()
    if not ok:
        raise HTTPException(status_code=503, detail="Binance ping failed")
    return {"ok": True}

@router.get("/status")
def binance_status():
    snap = status_snapshot()
    samples = {}
    for sym in ("BTCUSDT", "ETHUSDT", "BNBUSDT"):
        samples[sym] = futures_mark_price(sym)
    snap["samples"] = samples
    return snap

@router.get("/mark-price")
def mark_price(symbol: str = Query(..., min_length=6, max_length=20)):
    price = futures_mark_price(symbol)
    if price is None:
        raise HTTPException(status_code=503, detail="mark price unavailable")
    return {"symbol": symbol.upper(), "markPrice": price}













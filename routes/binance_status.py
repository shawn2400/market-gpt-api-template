# routes/binance_status.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from utils.auth import require_api_key
from utils.binance_client import status_snapshot, futures_mark_price

router = APIRouter(dependencies=[Depends(require_api_key)])

@router.get("/status")
def binance_status():
    snap = status_snapshot()
    # בדיקת דגימה זריזה ל-BTC/ETH/BNB (לא קריטי אם נכשל)
    samples = {}
    for sym in ("BTCUSDT", "ETHUSDT", "BNBUSDT"):
        price = futures_mark_price(sym)
        samples[sym] = price
    snap["samples"] = samples
    return snap

@router.get("/mark-price")
def mark_price(symbol: str = Query(..., min_length=6, max_length=20)):
    price = futures_mark_price(symbol)
    if price is None:
        raise HTTPException(status_code=503, detail="mark price unavailable")
    return {"symbol": symbol.upper(), "markPrice": price}






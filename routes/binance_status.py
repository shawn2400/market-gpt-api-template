# routes/binance_status.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from utils.auth import require_api_key
from utils.binance_client import status_snapshot, futures_mark_price, fapi_ping

router = APIRouter(prefix="/binance", dependencies=[Depends(require_api_key)])

@router.get("/ping", tags=["Binance"])
def ping():
    """בדיקת זמינות חיבור ל-Binance Futures"""
    return {"ok": fapi_ping()}

@router.get("/status", tags=["Binance"])
def binance_status():
    """
    מחזיר snapshot כללי על מצב Binance:
    - פינג
    - מפתחות API
    - מדגם Mark Price
    """
    snap = status_snapshot()
    samples = {}
    for sym in ("BTCUSDT", "ETHUSDT", "BNBUSDT"):
        try:
            samples[sym] = futures_mark_price(sym)
        except Exception:
            samples[sym] = None
    snap["samples"] = samples
    return snap

@router.get("/mark-price", tags=["Binance"])
def mark_price(symbol: str = Query(..., min_length=6, max_length=20)):
    """מחזיר Mark Price עדכני לסימבול"""
    price = futures_mark_price(symbol)
    if price is None:
        raise HTTPException(status_code=503, detail="mark price unavailable")
    return {"symbol": symbol.upper(), "markPrice": price}














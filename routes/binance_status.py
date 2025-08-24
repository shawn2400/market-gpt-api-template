# routes/binance_status.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from utils.auth import require_api_key
from utils.binance_client import (
    status_snapshot,
    futures_mark_price,
    futures_exchange_info_safe,
)

# כל הנתיבים כאן הם יחסיים לפריפיקס שיוגדר ב-main.py => "/binance"
router = APIRouter(dependencies=[Depends(require_api_key)])

@router.get("/status")
def binance_status():
    snap = status_snapshot()
    # דגימת מחירי mark (לא קריטי אם נכשל)
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

@router.get("/exchange-info")
def exchange_info(force_refresh: int = Query(0, ge=0, le=1)):
    try:
        info = futures_exchange_info_safe(force_refresh=bool(force_refresh))
        return {"count": len(info.get("symbols", [])), "data": info}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

@router.get("/ping")
def ping():
    return {"ok": True}








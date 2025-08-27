# routes/binance_status.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from utils.auth import require_api_key
from utils.binance_client import futures_mark_price, fapi_ping, futures_exchange_info_safe

router = APIRouter(
    prefix="/binance",
    tags=["Binance"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/ping")
def ping():
    """בודק זמינות Binance API"""
    try:
        return {"ok": fapi_ping()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ping failed: {e}")

@router.get("/status")
def binance_status():
    """
    סטטוס כללי של Binance Futures:
    - זמינות API
    - מחירי מדגם ל־BTC/ETH/BNB
    """
    try:
        samples = {}
        for sym in ("BTCUSDT", "ETHUSDT", "BNBUSDT"):
            samples[sym] = futures_mark_price(sym)
        return {"ok": True, "api": fapi_ping(), "samples": samples}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Binance status failed: {e}")

@router.get("/mark-price")
def mark_price(symbol: str = Query(..., min_length=6, max_length=20)):
    """מחזיר Mark Price לסימבול יחיד"""
    try:
        price = futures_mark_price(symbol)
        if price is None:
            raise HTTPException(status_code=503, detail=f"Mark price unavailable for {symbol}")
        return {"symbol": symbol.upper(), "markPrice": price}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch mark price: {e}")

@router.get("/exchange-info")
def exchange_info(force_refresh: int = Query(0, ge=0, le=1)):
    """מחזיר snapshot מלא של exchangeInfo (Binance Futures)."""
    try:
        return futures_exchange_info_safe(force_refresh=bool(force_refresh))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch exchange info: {e}")
















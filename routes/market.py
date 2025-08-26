# routes/market.py
from __future__ import annotations
from fastapi import APIRouter, Query, HTTPException
from utils.binance_client import get_symbol_info, futures_mark_price

router = APIRouter(prefix="/market", tags=["Market"])


@router.get("/symbol-info")
def symbol_info(symbol: str = Query(..., min_length=6, max_length=20)):
    """
    מחזיר מידע מלא על סימבול מה-Exchange Info של Binance Futures.
    """
    info = get_symbol_info(symbol)
    if not info:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    return {"symbol": symbol.upper(), "info": info}


@router.get("/mark-price")
def mark_price(symbol: str = Query(..., min_length=6, max_length=20)):
    """
    מחזיר Mark Price עדכני של סימבול מ-Binance Futures.
    """
    price = futures_mark_price(symbol)
    if price is None:
        raise HTTPException(status_code=503, detail="Mark price unavailable")
    return {"symbol": symbol.upper(), "markPrice": price}


















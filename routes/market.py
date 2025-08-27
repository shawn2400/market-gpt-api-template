# routes/market.py
from __future__ import annotations
from fastapi import APIRouter, Query, HTTPException, Depends
from utils.auth import require_api_key
from utils.binance_client import (
    get_symbol_info,
    futures_mark_price,
    futures_exchange_info_safe,
)

router = APIRouter(
    prefix="/market",
    tags=["Market"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/mark-price")
def mark_price(symbol: str = Query(..., min_length=6, max_length=20)):
    """מחזיר Mark Price עדכני לסימבול (Binance Futures)."""
    try:
        price = futures_mark_price(symbol)
        if price is None:
            raise HTTPException(status_code=503, detail=f"Mark price unavailable for {symbol}")
        return {"symbol": symbol.upper(), "markPrice": price}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch mark price: {e}")

@router.get("/symbol-info")
def symbol_info(
    symbol: str = Query(..., min_length=6, max_length=20),
    force_refresh: int = Query(0, ge=0, le=1),
):
    """מידע מלא על סימבול יחיד (minQty, tickSize, leverage וכו')."""
    try:
        info = get_symbol_info(symbol, force_refresh=bool(force_refresh))
        if not info:
            raise HTTPException(status_code=404, detail=f"Symbol info not found for {symbol}")
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch symbol info: {e}")

@router.get("/exchange-info")
def exchange_info(force_refresh: int = Query(0, ge=0, le=1)):
    """Snapshot מלא של exchangeInfo (Binance Futures)."""
    try:
        return futures_exchange_info_safe(force_refresh=bool(force_refresh))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch exchange info: {e}")























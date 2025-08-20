# routes/orders.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional

from utils import binance_client

router = APIRouter()

# ------------------------------
#        Spot Orders
# ------------------------------
@router.post("/spot/new")
async def spot_new_order(
    symbol: str,
    side: str,
    type: str,
    quantity: float,
    price: Optional[float] = None,
) -> Dict[str, Any]:
    """
    פתיחת פקודת SPOT ב-Binance.
    side: BUY / SELL
    type: LIMIT / MARKET
    """
    try:
        return binance_client.spot_new_order(
            symbol=symbol, side=side.upper(), type=type.upper(), quantity=quantity, price=price
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Spot order failed: {e}")


@router.get("/spot/balance/{asset}")
async def spot_balance(asset: str = "USDT") -> Dict[str, Any]:
    """החזרת יתרת SPOT לנכס מסוים"""
    bal = binance_client.spot_balance(asset)
    return {"asset": asset, "balance": bal}


# ------------------------------
#        Futures Orders
# ------------------------------
@router.post("/futures/new")
async def futures_new_order(
    symbol: str,
    side: str,
    type: str,
    quantity: float,
    price: Optional[float] = None,
) -> Dict[str, Any]:
    """
    פתיחת פקודת FUTURES ב-Binance.
    side: BUY / SELL
    type: LIMIT / MARKET / STOP
    """
    try:
        return binance_client.futures_new_order(
            symbol=symbol, side=side.upper(), type=type.upper(), quantity=quantity, price=price
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Futures order failed: {e}")


@router.get("/futures/balance/{asset}")
async def futures_balance(asset: str = "USDT") -> Dict[str, Any]:
    """החזרת יתרת FUTURES לנכס מסוים"""
    bal = binance_client.futures_balance(asset)
    return {"asset": asset, "balance": bal}


@router.get("/futures/position/{symbol}")
async def futures_position(symbol: str) -> Dict[str, Any]:
    """מצב פוזיציה FUTURES"""
    pos = binance_client.futures_position(symbol)
    if not pos:
        return {"symbol": symbol, "position": None}
    return pos


# ------------------------------
#        Grid Orders
# ------------------------------
@router.post("/grid")
async def grid_orders(
    symbol: str,
    side: str,
    start_price: float,
    end_price: float,
    steps: int,
    quantity: float,
) -> Dict[str, Any]:
    """
    מייצר פקודות גריד (Limit Orders) בין start_price ל-end_price.
    side: BUY / SELL
    """
    try:
        orders = binance_client.grid_orders(
            symbol=symbol, side=side.upper(), start_price=start_price, end_price=end_price, steps=steps, quantity=quantity
        )
        return {"symbol": symbol, "grid_orders": orders, "steps": steps}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Grid orders failed: {e}")


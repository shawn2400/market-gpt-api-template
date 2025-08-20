# routes/orders.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, Query, Body, HTTPException

try:
    from utils.auth import require_bearer_token
except Exception:
    async def require_bearer_token(*_a, **_k):
        raise HTTPException(status_code=401, detail="Unauthorized")

from utils import order_manager

router = APIRouter(
    prefix="/orders",
    tags=["Orders"],
    dependencies=[Depends(require_bearer_token)]
)

# ============================
#        Place Order
# ============================
@router.post("/place", summary="Place a new order")
async def place_order(
    req: Dict[str, Any] = Body(...)
) -> Dict[str, Any]:
    """
    Create a new order (spot or futures).
    Required fields: symbol, side, type, quantity
    """
    try:
        resp = order_manager.place_order(
            symbol=req["symbol"],
            market_type=req.get("market_type", "futures"),
            side=req["side"],
            order_type=req.get("type", "LIMIT"),
            quantity=float(req["quantity"]),
            price=float(req["price"]) if req.get("price") else None,
            time_in_force=req.get("timeInForce", "GTC"),
        )
        return {"ok": True, "order": resp}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================
#        Cancel Order
# ============================
@router.post("/cancel", summary="Cancel an order by ID")
async def cancel_order(
    symbol: str = Query(...),
    order_id: str = Query(...),
    market_type: str = Query("futures"),
) -> Dict[str, Any]:
    try:
        ok = order_manager.cancel_order(symbol, order_id, market_type)
        return {"ok": ok}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================
#     Get Open Orders
# ============================
@router.get("/open", summary="List open orders")
async def get_open_orders(
    symbol: str = Query(...),
    market_type: str = Query("futures"),
) -> Dict[str, Any]:
    try:
        orders = order_manager.get_open_orders(symbol, market_type)
        return {"ok": True, "orders": orders}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================
#     Order Status
# ============================
@router.get("/status", summary="Get order status")
async def order_status(
    symbol: str = Query(...),
    order_id: str = Query(...),
    market_type: str = Query("futures"),
) -> Dict[str, Any]:
    try:
        status = order_manager.order_status(symbol, order_id, market_type)
        return {"ok": True, "status": status}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================
#     Cancel All Orders
# ============================
@router.post("/cancel_all", summary="Cancel all open orders for symbol")
async def cancel_all_orders(
    symbol: str = Query(...),
    market_type: str = Query("futures"),
) -> Dict[str, Any]:
    try:
        count = order_manager.cancel_all(symbol, market_type)
        return {"ok": True, "cancelled": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}

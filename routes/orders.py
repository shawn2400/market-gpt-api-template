# routes/orders.py
from __future__ import annotations
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from utils.auth import require_api_key
from utils.binance_client import get_open_orders, get_all_orders

router = APIRouter(prefix="/orders", tags=["Orders"], dependencies=[Depends(require_api_key)])

class OrderModel(BaseModel):
    id: str
    symbol: str
    side: str
    qty: float
    price: float
    status: str
    leverage: Optional[int] = None
    created_at: Optional[str] = None

class OrdersSummary(BaseModel):
    ok: bool = True
    total: int
    returned: int
    items: List[OrderModel] = Field(default_factory=list)

def _map_order(o: dict) -> OrderModel:
    return OrderModel(
        id=str(o.get("orderId") or o.get("clientOrderId") or ""),
        symbol=str(o.get("symbol") or ""),
        side=str(o.get("side") or ""),
        qty=float(o.get("origQty") or o.get("cumQty") or 0.0),
        price=float(o.get("price") or o.get("stopPrice") or 0.0),
        status=str(o.get("status") or ""),
        leverage=None,
        created_at=str(o.get("time") or o.get("updateTime") or ""),
    )

@router.get("/open", response_model=OrdersSummary)
async def list_active_orders(
    symbol: Optional[str] = Query(None, description="Optional symbol filter"),
    limit: int = Query(200, ge=1, le=200, description="How many to return (max 200)"),
):
    data = get_open_orders(symbol=symbol)
    items = [_map_order(o) for o in (data or [])][:limit]
    return OrdersSummary(total=len(items), returned=len(items), items=items)

@router.get("/history", response_model=OrdersSummary)
async def list_orders_history(
    symbol: str = Query(..., description="Symbol is required for futures allOrders"),
    limit: int = Query(100, ge=1, le=500, description="How many to return (default 100, max 500)"),
):
    try:
        data = get_all_orders(symbol=symbol, limit=limit)
    except Exception as e:
        raise HTTPException(400, f"binance error: {e}")
    items = [_map_order(o) for o in (data or [])]
    return OrdersSummary(total=len(items), returned=len(items), items=items)























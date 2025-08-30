# routes/orders.py
from __future__ import annotations
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from utils.orders_manager import get_orders, get_active_orders

router = APIRouter(prefix="/orders", tags=["Orders"])

class OrderModel(BaseModel):
    id: str
    symbol: str
    side: str
    qty: float
    price: float
    status: str
    created_at: str
    simulated: bool = False
    clientOrderId: Optional[str] = None
    exchange: Optional[str] = None

class OrdersSummary(BaseModel):
    ok: bool = True
    total: int
    returned: int
    items: List[OrderModel] = Field(default_factory=list)

@router.get("/open", response_model=OrdersSummary)
async def list_open_orders(symbol: Optional[str] = Query(None, description="אופציונלי: סינון לפי סימבול")):
    items = [OrderModel(**o) for o in get_active_orders(symbol=symbol)]
    return OrdersSummary(total=len(items), returned=len(items), items=items)

@router.get("/history", response_model=OrdersSummary)
async def list_orders_history(
    symbol: Optional[str] = Query(None, description="אופציונלי: סינון לפי סימבול"),
    limit: int = Query(50, ge=1, le=200, description="כמה להחזיר (ברירת מחדל 50, מקס' 200)"),
):
    raw = get_orders(limit=limit, symbol=symbol)
    items = [OrderModel(**o) for o in raw]
    return OrdersSummary(total=len(items), returned=len(items), items=items)














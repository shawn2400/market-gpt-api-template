# routes/orders.py
from __future__ import annotations

from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel, Field
from typing import List

from utils.orders_manager import get_orders, get_active_orders
from utils.auth import require_api_key

router = APIRouter(
    prefix="/orders",
    tags=["Orders"],
    dependencies=[Depends(require_api_key)],
)

class OrderModel(BaseModel):
    id: str
    symbol: str
    side: str
    qty: float
    price: float
    status: str
    created_at: str

class OrdersSummary(BaseModel):
    ok: bool = True
    total: int
    returned: int
    items: List[OrderModel] = Field(default_factory=list)

@router.get("/history", response_model=OrdersSummary)
async def list_orders(
    symbol: str | None = Query(None, description="סינון לפי סימבול (אופציונלי)"),
    limit: int = Query(50, ge=1, le=200, description="כמה להזיז להיסטוריה (ברירת מחדל 50)"),
):
    orders = get_orders(limit=limit)
    if symbol:
        s = symbol.strip().upper()
        orders = [o for o in orders if (o.get("symbol") or "").upper() == s]
    items = [OrderModel(**o) for o in orders[:limit]]
    return OrdersSummary(total=len(items), returned=len(items), items=items)

@router.get("/open", response_model=OrdersSummary)
async def list_active():
    orders = get_active_orders()
    items = [OrderModel(**o) for o in orders]
    return OrdersSummary(total=len(items), returned=len(items), items=items)












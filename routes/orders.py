# routes/orders.py
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import List
from utils.orders_manager import get_orders, get_active_orders

router = APIRouter(tags=["Orders"])


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


@router.get("/", response_model=OrdersSummary)
async def list_orders(
    limit: int = Query(50, ge=1, le=200, description="כמה הזמנות להחזיר (ברירת מחדל 50, מקסימום 200)")
):
    """
    מחזיר את ההזמנות האחרונות בלבד (מוגבל ל־200).
    """
    orders = get_orders(limit=limit)
    total = len(orders)
    items = [OrderModel(**o) for o in orders[:limit]]
    return OrdersSummary(total=total, returned=len(items), items=items)


@router.get("/active", response_model=OrdersSummary)
async def list_active_orders():
    """
    מחזיר את ההזמנות הפתוחות בלבד.
    """
    orders = get_active_orders()
    total = len(orders)
    items = [OrderModel(**o) for o in orders]
    return OrdersSummary(total=total, returned=len(items), items=items)







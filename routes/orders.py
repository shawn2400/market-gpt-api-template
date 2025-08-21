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


class OrdersResponse(BaseModel):
    ok: bool = True
    count_total: int
    returned: int
    items: List[OrderModel] = Field(default_factory=list)


@router.get("/", response_model=OrdersResponse)
async def list_orders(limit: int = Query(50, ge=1, le=200)):
    """
    מחזיר את ההזמנות האחרונות (ברירת מחדל 50, מקסימום 200).
    """
    orders = get_orders(limit=limit)
    total = len(orders)
    clean = [OrderModel(**o) for o in orders[:limit]]
    return OrdersResponse(count_total=total, returned=len(clean), items=clean)


@router.get("/active", response_model=OrdersResponse)
async def list_active_orders():
    """
    מחזיר את ההזמנות הפתוחות בלבד.
    """
    orders = get_active_orders()
    total = len(orders)
    clean = [OrderModel(**o) for o in orders]
    return OrdersResponse(count_total=total, returned=len(clean), items=clean)





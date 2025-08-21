# routes/orders.py
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import List
from utils.orders_manager import get_orders, get_active_orders

router = APIRouter()

class OrderModel(BaseModel):
    id: str
    symbol: str
    side: str
    qty: float
    price: float
    status: str
    created_at: str

@router.get("/", response_model=List[OrderModel])
async def list_orders(limit: int = Query(50, ge=1, le=200)):
    """
    מחזיר את ההזמנות האחרונות (ברירת מחדל 50, מקסימום 200).
    """
    orders = get_orders(limit=limit)
    return [OrderModel(**o) for o in orders]

@router.get("/active", response_model=List[OrderModel])
async def list_active_orders():
    """
    מחזיר את ההזמנות הפתוחות בלבד.
    """
    orders = get_active_orders()
    return [OrderModel(**o) for o in orders]




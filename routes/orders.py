# routes/orders.py
from __future__ import annotations
from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
from utils.auth import require_api_key
from utils.orders_manager import get_orders, get_active_orders

router = APIRouter(prefix="/orders", tags=["Orders"], dependencies=[Depends(require_api_key)])

class OrderModel(BaseModel):
    id: str
    symbol: str
    side: str
    qty: float
    price: float
    status: str
    leverage: Optional[int] = None
    created_at: str

class OrdersSummary(BaseModel):
    ok: bool = True
    total: int
    returned: int
    items: List[OrderModel] = Field(default_factory=list)

@router.get("/history", response_model=OrdersSummary)
async def list_orders(
    symbol: Optional[str] = Query(None, description="Optional symbol filter"),
    limit: int = Query(50, ge=1, le=200, description="How many to return (default 50, max 200)"),
):
    items = [OrderModel(**o) for o in get_orders(limit=limit, symbol=symbol)]
    return OrdersSummary(total=len(items), returned=len(items), items=items)

@router.get("/open", response_model=OrdersSummary)
async def list_active_orders(
    symbol: Optional[str] = Query(None, description="Optional symbol filter"),
    limit: int = Query(200, ge=1, le=200, description="How many to return (max 200)"),
):
    items = [OrderModel(**o) for o in get_active_orders(limit=limit, symbol=symbol)]
    return OrdersSummary(total=len(items), returned=len(items), items=items)





















# routes/orders.py
from __future__ import annotations
from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

from utils.auth import require_api_key
from utils.orders_manager import get_orders, get_active_orders

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
    client_id: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None

class OrdersSummary(BaseModel):
    ok: bool = True
    total: int
    returned: int
    items: List[OrderModel] = Field(default_factory=list)

# היסטוריה (עם סינון סימבול + limit)
@router.get("/history", response_model=OrdersSummary)
async def list_history(symbol: Optional[str] = Query(None), limit: int = Query(50, ge=1, le=200)):
    items = [OrderModel(**o) for o in get_orders(symbol=symbol, limit=limit)]
    return OrdersSummary(total=len(items), returned=len(items), items=items)

# פתוחות
@router.get("/open", response_model=OrdersSummary)
async def list_open():
    items = [OrderModel(**o) for o in get_active_orders()]
    return OrdersSummary(total=len(items), returned=len(items), items=items)

# תאימות לאחור: "/" -> history, "/active" -> open
@router.get("/", response_model=OrdersSummary)
async def root_history(limit: int = Query(50, ge=1, le=200)):
    items = [OrderModel(**o) for o in get_orders(limit=limit)]
    return OrdersSummary(total=len(items), returned=len(items), items=items)

@router.get("/active", response_model=OrdersSummary)
async def legacy_active():
    items = [OrderModel(**o) for o in get_active_orders()]
    return OrdersSummary(total=len(items), returned=len(items), items=items)









# routes/orders.py
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from utils.orders_manager import get_orders, get_active_orders, clear_history

router = APIRouter(prefix="/orders", tags=["Orders"])

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
    items: List[OrderModel] = Field(default_factory=list)

@router.get("/open", response_model=OrdersSummary)
async def list_open(symbol: Optional[str] = Query(None, description="סינון לפי סימבול (אופציונלי)")):
    items = [OrderModel(**o) for o in get_active_orders(symbol=symbol)]
    return OrdersSummary(total=len(items), items=items)

@router.get("/history", response_model=OrdersSummary)
async def history(
    symbol: Optional[str] = Query(None, description="סינון לפי סימבול (אופציונלי)"),
    limit: int = Query(50, ge=1, le=200, description="ברירת מחדל 50, מקסימום 200"),
):
    rows = get_orders(limit=limit, symbol=symbol)
    items = [OrderModel(**o) for o in rows]
    return OrdersSummary(total=len(items), items=items)

@router.delete("/history/clear")
async def history_clear():
    n = clear_history()
    return {"ok": True, "cleared": n}
















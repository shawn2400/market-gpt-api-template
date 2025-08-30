# routes/orders.py
from __future__ import annotations
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from utils.auth import require_api_key
from utils.binance_client import (
    get_open_orders, get_order, cancel_order, cancel_all_open_orders, all_orders
)

router = APIRouter(
    prefix="/orders",
    tags=["Orders"],
    dependencies=[Depends(require_api_key)],
)

# --- Models (תצוגה קלה) ---

class OrderItem(BaseModel):
    orderId: int
    symbol: str
    side: str
    price: float
    origQty: float
    executedQty: float
    status: str
    type: str = Field(default="LIMIT")
    timeInForce: Optional[str] = None
    updateTime: Optional[int] = None
    clientOrderId: Optional[str] = None
    reduceOnly: Optional[bool] = None
    positionSide: Optional[str] = None

def _fnum(x, d=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return d

def _map_order(o: Dict[str, Any]) -> OrderItem:
    return OrderItem(
        orderId=int(o.get("orderId")),
        symbol=str(o.get("symbol") or ""),
        side=str(o.get("side") or ""),
        price=_fnum(o.get("price")),
        origQty=_fnum(o.get("origQty")),
        executedQty=_fnum(o.get("executedQty")),
        status=str(o.get("status") or ""),
        type=str(o.get("type") or "LIMIT"),
        timeInForce=o.get("timeInForce"),
        updateTime=o.get("updateTime"),
        clientOrderId=o.get("clientOrderId") or o.get("origClientOrderId"),
        reduceOnly=(str(o.get("reduceOnly")).lower() == "true") if ("reduceOnly" in o) else None,
        positionSide=o.get("positionSide"),
    )

class OrdersList(BaseModel):
    ok: bool = True
    total: int
    items: List[OrderItem] = Field(default_factory=list)

# --- Endpoints ---

@router.get("/open", response_model=OrdersList)
def list_open_orders(symbol: Optional[str] = Query(None, description="סינון לפי סימבול (אופציונלי)")):
    try:
        raw = get_open_orders(symbol)
        items = [_map_order(o) for o in (raw or [])]
        return OrdersList(total=len(items), items=items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"openOrders failed: {e}")

@router.get("/get", response_model=OrderItem)
def get_single_order(
    symbol: str = Query(...),
    order_id: Optional[int] = Query(None),
    client_id: Optional[str] = Query(None),
):
    if not order_id and not client_id:
        raise HTTPException(status_code=400, detail="must supply order_id or client_id")
    try:
        o = get_order(symbol, order_id=order_id, client_id=client_id)
        return _map_order(o)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"get order failed: {e}")

@router.delete("/cancel", response_model=OrderItem)
def cancel_single_order(
    symbol: str = Query(...),
    order_id: Optional[int] = Query(None),
    client_id: Optional[str] = Query(None),
):
    if not order_id and not client_id:
        raise HTTPException(status_code=400, detail="must supply order_id or client_id")
    try:
        o = cancel_order(symbol, order_id=order_id, client_id=client_id)
        return _map_order(o)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cancel order failed: {e}")

@router.delete("/cancel_all", response_model=OrdersList)
def cancel_all(symbol: str = Query(...)):
    try:
        raw = cancel_all_open_orders(symbol)
        if isinstance(raw, list):
            items = [_map_order(o) for o in raw]
            return OrdersList(total=len(items), items=items)
        items = [_map_order(o) for o in (raw.get("orders", []) if isinstance(raw, dict) else [])]
        return OrdersList(total=len(items), items=items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cancel all failed: {e}")

@router.get("/history", response_model=OrdersList)
def list_history(
    symbol: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    start_time: Optional[int] = Query(None, description="מילישניות Unix (אופציונלי)"),
    end_time: Optional[int] = Query(None, description="מילישניות Unix (אופציונלי)"),
):
    try:
        raw = all_orders(symbol, limit=limit, start_time=start_time, end_time=end_time)
        items = [_map_order(o) for o in (raw or [])]
        return OrdersList(total=len(items), items=items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"history failed: {e}")








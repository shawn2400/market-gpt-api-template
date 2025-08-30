# utils/orders_manager.py
from __future__ import annotations
import threading, uuid
from typing import Optional, List, Dict
from collections import deque
from datetime import datetime, timezone

_Order = Dict[str, object]

_LOCK = threading.Lock()
# נשמור עד 1000 הזמנות בזיכרון (קליל ומהיר)
_ORDERS: deque[_Order] = deque(maxlen=1000)

_OPEN_STATUSES = {"NEW", "OPEN", "PARTIALLY_FILLED"}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def record_order(
    *,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    status: str = "SIMULATED",
    leverage: Optional[int] = None,
    client_order_id: Optional[str] = None,
) -> _Order:
    o: _Order = {
        "id": client_order_id or uuid.uuid4().hex,
        "symbol": symbol.upper(),
        "side": side.upper(),
        "qty": float(qty),
        "price": float(price),
        "status": status,
        "leverage": int(leverage) if leverage else None,
        "created_at": _now_iso(),
    }
    with _LOCK:
        _ORDERS.append(o)
    return o

def record_simulated_order(
    *, symbol: str, side: str, qty: float, price: float, leverage: Optional[int] = None
) -> _Order:
    return record_order(
        symbol=symbol, side=side, qty=qty, price=price, leverage=leverage, status="SIMULATED"
    )

def get_orders(*, limit: int = 50, symbol: Optional[str] = None) -> List[_Order]:
    sym = (symbol or "").strip().upper() or None
    with _LOCK:
        items = list(_ORDERS)
    if sym:
        items = [o for o in items if str(o.get("symbol")).upper() == sym]
    items = list(reversed(items))  # אחרונות קודם
    return items[:max(1, min(200, limit))]

def get_active_orders(*, symbol: Optional[str] = None, limit: int = 200) -> List[_Order]:
    sym = (symbol or "").strip().upper() or None
    with _LOCK:
        items = [o for o in _ORDERS if str(o.get("status")) in _OPEN_STATUSES]
    if sym:
        items = [o for o in items if str(o.get("symbol")).upper() == sym]
    items = list(reversed(items))
    return items[:max(1, min(200, limit))]








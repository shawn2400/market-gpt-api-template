# utils/orders_manager.py
from __future__ import annotations
import threading, uuid, time
from typing import Optional, List, Dict
from collections import deque
from datetime import datetime, timezone
from utils.metrics import metrics_tracker

_Order = Dict[str, object]

_LOCK = threading.Lock()
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
    mark_price: Optional[float] = None,
    elapsed_ms: Optional[float] = None,
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
    if mark_price is not None:
        o["mark_price"] = float(mark_price)
        o["slippage_bps"] = round(((price - mark_price) / mark_price) * 1e4, 3)
    if elapsed_ms is not None:
        o["latency_ms"] = round(elapsed_ms, 2)

    with _LOCK:
        _ORDERS.append(o)

    # Track in metrics (TCA)
    if "slippage_bps" in o:
        metrics_tracker.observe_slippage(o["slippage_bps"])
    if "latency_ms" in o:
        metrics_tracker.observe_order_latency(o["latency_ms"])

    return o

def record_simulated_order(symbol: str, side: str, qty: float, price: float, leverage: Optional[int] = None) -> _Order:
    return record_order(symbol=symbol, side=side, qty=qty, price=price, leverage=leverage, status="SIMULATED")

def get_orders(limit: int = 50, symbol: Optional[str] = None) -> List[_Order]:
    sym = (symbol or "").strip().upper() or None
    with _LOCK:
        items = list(_ORDERS)
    if sym:
        items = [o for o in items if str(o.get("symbol")).upper() == sym]
    return list(reversed(items))[:max(1, min(200, limit))]

def get_active_orders(symbol: Optional[str] = None, limit: int = 200) -> List[_Order]:
    sym = (symbol or "").strip().upper() or None
    with _LOCK:
        items = [o for o in _ORDERS if str(o.get("status")) in _OPEN_STATUSES]
    if sym:
        items = [o for o in items if str(o.get("symbol")).upper() == sym]
    return list(reversed(items))[:max(1, min(200, limit))]










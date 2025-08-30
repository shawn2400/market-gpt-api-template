# utils/orders_manager.py
from __future__ import annotations

import time
import threading
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict
from collections import deque
from datetime import datetime, timezone

_MAX = 200  # שמור עד 200 פריטים בזיכרון (ללא עומס)
_lock = threading.Lock()
_store: deque = deque(maxlen=_MAX)

ACTIVE_STATUSES = {"NEW", "PARTIALLY_FILLED", "PENDING_NEW", "SIMULATED"}  # SIMULATED = dry-run

@dataclass
class OrderRec:
    id: str
    symbol: str
    side: str
    qty: float
    price: float
    status: str
    created_at: str
    client_id: Optional[str] = None
    dry_run: bool = False
    tif: Optional[str] = None  # GTC/IOC/FOK/GTX וכו'

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def record_order(
    *,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    status: str,
    order_id: str,
    client_id: Optional[str],
    dry_run: bool,
    tif: Optional[str] = None,
) -> None:
    rec = OrderRec(
        id=str(order_id),
        symbol=symbol.upper(),
        side=side.upper(),
        qty=float(qty),
        price=float(price),
        status=status.upper(),
        created_at=_now_iso(),
        client_id=client_id,
        dry_run=bool(dry_run),
        tif=tif,
    )
    with _lock:
        _store.append(rec)

def update_order_status(order_id: str, status: str) -> None:
    status = status.upper()
    with _lock:
        for i in range(len(_store) - 1, -1, -1):
            if _store[i].id == str(order_id):
                _store[i].status = status
                break

def get_orders(*, limit: int = 50, symbol: Optional[str] = None) -> List[Dict]:
    limit = max(1, min(int(limit), _MAX))
    with _lock:
        items = list(_store)
    if symbol:
        sym = symbol.upper()
        items = [o for o in items if o.symbol == sym]
    # מהחדש לישן
    items = items[::-1][:limit]
    return [asdict(o) for o in items]

def get_active_orders(*, symbol: Optional[str] = None) -> List[Dict]:
    with _lock:
        items = list(_store)
    if symbol:
        sym = symbol.upper()
        items = [o for o in items if o.symbol == sym]
    items = [o for o in items if o.status in ACTIVE_STATUSES]
    # מהחדש לישן
    items = items[::-1]
    return [asdict(o) for o in items]










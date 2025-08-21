# utils/orders_manager.py
import time
import json
from typing import List, Dict
from utils.redis_client import redis_client

ORDERS_KEY = "orders:all"

def _load_orders() -> List[Dict]:
    if not redis_client:
        return []
    try:
        raw = redis_client.get(ORDERS_KEY)
        return json.loads(raw) if raw else []
    except Exception:
        return []

def _save_orders(orders: List[Dict]) -> None:
    if not redis_client:
        return
    try:
        redis_client.set(ORDERS_KEY, json.dumps(orders), ex=86400)
    except Exception:
        pass

def get_orders(limit: int = 50) -> List[Dict]:
    orders = _load_orders()
    return list(reversed(orders))[:limit]

def get_active_orders() -> List[Dict]:
    orders = _load_orders()
    return [o for o in orders if o.get("status") in ("NEW", "PARTIALLY_FILLED")]

def add_order(symbol: str, side: str, qty: float, price: float) -> Dict:
    order = {
        "id": str(int(time.time() * 1000)),
        "symbol": symbol.upper(),
        "side": side.upper(),
        "qty": qty,
        "price": price,
        "status": "NEW",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    orders = _load_orders()
    orders.append(order)
    _save_orders(orders)
    return order

# utils/orders_manager.py
from __future__ import annotations

import json
import os
import time
import threading
from typing import Any, Dict, List, Optional

try:
    import redis  # type: ignore
except Exception:
    redis = None  # gracefully fallback

REDIS_URL = os.getenv("REDIS_URL", "").strip()

# ─────────────────────────────────────────────────────────────────────────────
# Backend: Redis (אם קיים) או זיכרון מקומי
# ─────────────────────────────────────────────────────────────────────────────
_r: Optional["redis.Redis"] = None
_mem_lock = threading.Lock()
_mem_orders: List[Dict[str, Any]] = []  # newest first
_MEM_MAX = 500

def _connect_redis() -> Optional["redis.Redis"]:
    if not (redis and REDIS_URL):
        return None
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

def _make_id() -> str:
    # monotonic-ish id
    return f"sim-{int(time.time()*1000)}"

def _ensure_backend():
    global _r
    if _r is None:
        _r = _connect_redis()

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def save_simulated_order(symbol: str, side: str, qty: float, price: float, status: str = "SIMULATED") -> Dict[str, Any]:
    """
    רושם הזמנת סימולציה להיסטוריה (ללא פתיחה אמיתית בבורסה).
    אם Redis קיים – משתמשים בו (רשימת orders:history), אחרת בזיכרון מקומי.
    """
    _ensure_backend()
    order = {
        "id": _make_id(),
        "symbol": (symbol or "").upper(),
        "side": (side or "").upper(),
        "qty": float(qty),
        "price": float(price),
        "status": status,
        "created_at": _now_iso(),
    }

    if _r:
        try:
            _r.lpush("orders:history", json.dumps(order))
            _r.ltrim("orders:history", 0, _MEM_MAX - 1)
            return order
        except Exception:
            pass  # fallback to memory

    with _mem_lock:
        _mem_orders.insert(0, order)
        if len(_mem_orders) > _MEM_MAX:
            _mem_orders.pop()
    return order

def get_orders(limit: int = 50, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    מחזיר הזמנות מהחדשות לישנות. אם symbol סופק – מסנן לפי סימבול.
    """
    _ensure_backend()
    raw: List[Dict[str, Any]] = []
    if _r:
        try:
            items = _r.lrange("orders:history", 0, max(0, limit*3))  # מעט-יתר, לסינון לפי symbol
            for s in items:
                try:
                    raw.append(json.loads(s))
                except Exception:
                    continue
        except Exception:
            pass

    if not raw:
        with _mem_lock:
            raw = list(_mem_orders)  # copy

    if symbol:
        sym = symbol.strip().upper()
        raw = [o for o in raw if (o.get("symbol") or "").upper() == sym]

    return raw[: max(1, min(200, int(limit)))]

def get_active_orders(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    סימולציה בלבד: מגדיר ACTIVE כמצבים 'NEW', 'OPEN', 'PARTIALLY_FILLED'.
    הזמנות SIMULATED יוחזרו כהיסטוריה (לא ACTIVE).
    """
    act = {"NEW", "OPEN", "PARTIALLY_FILLED"}
    orders = get_orders(limit=200, symbol=symbol)
    return [o for o in orders if (o.get("status") or "").upper() in act]






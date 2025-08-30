# utils/orders_manager.py
from __future__ import annotations

import os
import json
import time
import uuid
import threading
from typing import Any, Dict, List

_REDIS_URL = os.getenv("REDIS_URL", "").strip()
_REDIS = None
if _REDIS_URL:
    try:
        import redis  # type: ignore
        _REDIS = redis.from_url(_REDIS_URL, decode_responses=True)
        try:
            _REDIS.ping()
        except Exception:
            _REDIS = None
    except Exception:
        _REDIS = None

_LOCK = threading.Lock()
_MEM_ORDERS: List[Dict[str, Any]] = []

_ORDERS_KEY = os.getenv("ORDERS_KEY", "algogpt:orders")
_MAX_ORDERS = int(os.getenv("ORDERS_MAX", "200"))

_ACTIVE_STATUSES = {"NEW", "PENDING_NEW", "PARTIALLY_FILLED", "OPEN", "PENDING"}

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def _normalize(order: Dict[str, Any]) -> Dict[str, Any]:
    o = dict(order or {})
    o.setdefault("id", o.get("orderId") or o.get("clientOrderId") or str(uuid.uuid4()))
    o.setdefault("symbol", "")
    o.setdefault("side", "")
    o.setdefault("qty", _f(o.get("quantity") or o.get("qty"), 0.0))
    o.setdefault("price", _f(o.get("price") or o.get("entry"), 0.0))
    o.setdefault("status", str(o.get("status") or o.get("state") or (o.get("simulated") and "SIMULATED") or "NEW"))
    o.setdefault("created_at", o.get("created_at") or _now_iso())
    return o

def record_order(order: Dict[str, Any]) -> None:
    o = _normalize(order)
    if _REDIS is not None:
        pip = _REDIS.pipeline()
        pip.lpush(_ORDERS_KEY, json.dumps(o, ensure_ascii=False))
        pip.ltrim(_ORDERS_KEY, 0, _MAX_ORDERS - 1)
        try:
            pip.execute()
            return
        except Exception:
            pass
    with _LOCK:
        _MEM_ORDERS.insert(0, o)
        del _MEM_ORDERS[_MAX_ORDERS:]

def get_orders(limit: int = 50) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, _MAX_ORDERS))
    if _REDIS is not None:
        try:
            raw = _REDIS.lrange(_ORDERS_KEY, 0, limit - 1)
            out: List[Dict[str, Any]] = []
            for r in raw:
                try:
                    out.append(json.loads(r))
                except Exception:
                    pass
            return out
        except Exception:
            pass
    with _LOCK:
        return [dict(o) for o in _MEM_ORDERS[:limit]]

def get_active_orders() -> List[Dict[str, Any]]:
    orders = get_orders(limit=_MAX_ORDERS)
    return [o for o in orders if str(o.get("status", "")).upper() in _ACTIVE_STATUSES]




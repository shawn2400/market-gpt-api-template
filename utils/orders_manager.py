# utils/orders_manager.py
from __future__ import annotations

import os, json, time, uuid, logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger("algogpt.orders")

# Redis (אופציונלי) + Fallback לזיכרון
REDIS_URL = os.getenv("REDIS_URL", "").strip()
_R = None
if REDIS_URL:
    try:
        import redis  # type: ignore
        _R = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        _R.ping()
        logger.info("[Orders] Redis backend: %s", REDIS_URL)
    except Exception as e:
        _R = None
        logger.info("[Orders] Redis unavailable → in-memory (%s)", e)

_LIST_KEY = "algogpt:orders"
_ORDERS: List[Dict[str, Any]] = []  # fallback in-memory (עד 1000 אחרונות)

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def _persist(order: Dict[str, Any]) -> None:
    if _R:
        try:
            _R.lpush(_LIST_KEY, json.dumps(order))
            _R.ltrim(_LIST_KEY, 0, 999)
            return
        except Exception as e:
            logger.warning({"event": "orders_redis_write_failed", "error": str(e)})
    _ORDERS.insert(0, order)
    del _ORDERS[1000:]

def _load_all() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if _R:
        try:
            vals = _R.lrange(_LIST_KEY, 0, 999) or []
            out.extend(json.loads(v) for v in vals)
        except Exception as e:
            logger.warning({"event": "orders_redis_read_failed", "error": str(e)})
    out.extend(_ORDERS)
    seen = set()
    unique: List[Dict[str, Any]] = []
    for o in out:
        oid = str(o.get("id") or "")
        if oid and oid not in seen:
            seen.add(oid)
            unique.append(o)
    return unique

def add_order_local(
    *,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    status: str = "NEW",
    simulated: bool = False,
    order_id: Optional[str] = None,
    client_order_id: Optional[str] = None,
    exchange: str = "BINANCE_FUTURES",
) -> Dict[str, Any]:
    oid = order_id or f"loc-{uuid.uuid4().hex[:12]}"
    item = {
        "id": oid,
        "symbol": symbol.upper().strip(),
        "side": side.upper().strip(),
        "qty": float(qty),
        "price": float(price),
        "status": status,  # NEW / PARTIALLY_FILLED / FILLED / CANCELED
        "simulated": bool(simulated),
        "clientOrderId": client_order_id,
        "exchange": exchange,
        "created_at": _now_iso(),
    }
    _persist(item)
    return item

def get_orders(*, limit: int = 50, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    items = _load_all()
    if symbol:
        s = symbol.upper().strip()
        items = [o for o in items if (o.get("symbol") or "").upper() == s]
    return items[: max(1, min(200, int(limit)))]

def get_active_orders(*, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    active_states = {"NEW", "PARTIALLY_FILLED", "PENDING", "ACCEPTED"}
    items = _load_all()
    items = [o for o in items if str(o.get("status") or "").upper() in active_states]
    if symbol:
        s = symbol.upper().strip()
        items = [o for o in items if (o.get("symbol") or "").upper() == s]
    return items[:200]






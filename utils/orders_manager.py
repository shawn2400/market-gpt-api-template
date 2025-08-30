# utils/orders_manager.py
from __future__ import annotations

import os, json, time, uuid, threading
from typing import Optional, List, Dict, Any

try:
    import redis  # type: ignore
except Exception:
    redis = None  # optional

REDIS_URL = os.getenv("REDIS_URL")
_USE_REDIS = bool(REDIS_URL and redis is not None)

_LOCK = threading.RLock()
_MEM_HISTORY: List[Dict[str, Any]] = []

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

def _redis_client():
    if not _USE_REDIS:
        return None
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)

_HISTORY_KEY = "orders:history"  # RPUSH JSON dicts (newest at tail)

_TERMINAL = {"FILLED", "CANCELED", "REJECTED", "EXPIRED", "EXPIRED_IN_MATCH", "SIMULATED_CLOSED"}

def _push(item: Dict[str, Any]) -> None:
    if _USE_REDIS:
        r = _redis_client()
        r.rpush(_HISTORY_KEY, json.dumps(item))
        r.ltrim(_HISTORY_KEY, -2000, -1)  # keep last N
    else:
        with _LOCK:
            _MEM_HISTORY.append(item)
            if len(_MEM_HISTORY) > 2000:
                del _MEM_HISTORY[:-2000]

def _read_all() -> List[Dict[str, Any]]:
    if _USE_REDIS:
        r = _redis_client()
        vals = r.lrange(_HISTORY_KEY, 0, -1)
        return [json.loads(v) for v in vals]
    else:
        with _LOCK:
            return list(_MEM_HISTORY)

def append_simulated_order(*, symbol: str, side: str, qty: float, price: float, tif: str = "GTC") -> Dict[str, Any]:
    oid = f"sim-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}"
    item = {
        "id": oid,
        "symbol": symbol.upper(),
        "side": side.upper(),
        "qty": float(qty),
        "price": float(price),
        "status": "SIMULATED",
        "tif": tif,
        "source": "dry_run",
        "created_at": _now_iso(),
    }
    _push(item)
    return item

def append_real_order(resp: Dict[str, Any]) -> Dict[str, Any]:
    # Accepts Binance response of /fapi/v1/order (RESULT/ACK/FULL)
    item = {
        "id": str(resp.get("orderId") or resp.get("clientOrderId") or f"ord-{uuid.uuid4().hex[:8]}"),
        "symbol": (resp.get("symbol") or "").upper(),
        "side": (resp.get("side") or "").upper(),
        "qty": float(resp.get("origQty") or resp.get("executedQty") or 0.0),
        "price": float(resp.get("price") or 0.0),
        "status": (resp.get("status") or "NEW"),
        "tif": resp.get("timeInForce") or "GTC",
        "source": "binance",
        "created_at": _now_iso(),
    }
    _push(item)
    return item

def get_orders(limit: int = 50, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    items = _read_all()
    if symbol:
        s = symbol.upper()
        items = [it for it in items if it.get("symbol") == s]
    # history newest last -> return last 'limit'
    return items[-limit:] if limit and limit > 0 else items

def get_active_orders(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    items = _read_all()
    if symbol:
        s = symbol.upper()
        items = [it for it in items if it.get("symbol") == s]
    items = [it for it in items if str(it.get("status") or "").upper() not in _TERMINAL]
    return items

def clear_history() -> int:
    if _USE_REDIS:
        r = _redis_client()
        n = r.llen(_HISTORY_KEY)
        r.delete(_HISTORY_KEY)
        return int(n or 0)
    else:
        with _LOCK:
            n = len(_MEM_HISTORY)
            _MEM_HISTORY.clear()
            return n






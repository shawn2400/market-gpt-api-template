# utils/trade_store.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
import os, json, time, logging
from utils.redis_client import redis_client as RED

logger = logging.getLogger("algogpt.trade_store")

USE_REDIS_TRADES = os.getenv("USE_REDIS_TRADES", "0").lower() in ("1", "true", "yes")

_TRADES_MEM: Dict[str, Dict[str, Any]] = {}

def _key(tid: str) -> str:
    return f"trades:active:{tid}"

def _set_key() -> str:
    return "trades:active:set"

def _encode_map(item: Dict[str, Any]) -> Dict[str, str]:
    m: Dict[str, str] = {}
    for k, v in item.items():
        if isinstance(v, (dict, list)):
            m[k] = json.dumps(v, ensure_ascii=False)
        else:
            m[k] = str(v)
    return m

def _decode_map(d: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (d or {}).items():
        if isinstance(v, bytes):
            v = v.decode("utf-8", "ignore")
        if isinstance(k, bytes):
            k = k.decode("utf-8", "ignore")
        if isinstance(v, str) and v and v[0] in "[{":
            try:
                out[k] = json.loads(v)
                continue
            except Exception:
                pass
        try:
            if v is None:
                out[k] = v
            elif str(v).isdigit():
                out[k] = int(v)
            else:
                out[k] = float(v)
                continue
        except Exception:
            out[k] = v
    return out

def create_trade(item: Dict[str, Any]) -> None:
    tid = str(item.get("trade_id"))
    if not tid:
        raise ValueError("missing trade_id")
    item = dict(item)
    item.setdefault("status", "active")
    item.setdefault("ts", int(time.time()))
    if USE_REDIS_TRADES and RED:
        RED.hset(_key(tid), mapping=_encode_map(item))
        RED.sadd(_set_key(), tid)
    else:
        _TRADES_MEM[tid] = item

def get_trade(tid: str) -> Optional[Dict[str, Any]]:
    if USE_REDIS_TRADES and RED:
        d = RED.hgetall(_key(tid))
        return _decode_map(d) if d else None
    return _TRADES_MEM.get(tid)

def update_trade(tid: str, updates: Dict[str, Any]) -> None:
    if USE_REDIS_TRADES and RED:
        if not RED.exists(_key(tid)):
            return
        current = _decode_map(RED.hgetall(_key(tid)))
        current.update(updates)
        RED.hset(_key(tid), mapping=_encode_map(current))
    else:
        if tid in _TRADES_MEM:
            _TRADES_MEM[tid].update(updates)

def list_active(limit: int = 1000) -> List[Dict[str, Any]]:
    if USE_REDIS_TRADES and RED:
        tids = list(RED.smembers(_set_key()) or [])
        out: List[Dict[str, Any]] = []
        for tid in tids[:limit]:
            if isinstance(tid, bytes):
                tid = tid.decode("utf-8", "ignore")
            d = RED.hgetall(_key(tid))
            if d:
                out.append(_decode_map(d))
        out.sort(key=lambda r: int(r.get("ts") or 0), reverse=True)
        return out
    out = list(_TRADES_MEM.values())
    out.sort(key=lambda r: int(r.get("ts") or 0), reverse=True)
    return out[:limit]



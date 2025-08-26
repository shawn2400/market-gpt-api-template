# utils/trade_store.py
from __future__ import annotations
import json, time, uuid
from typing import Dict, Any, List, Optional

try:
    from utils.redis_client import redis_client as RED
except Exception:
    RED = None

NS = "algogpt:trades"  # namespace
TTL_SEC = 14 * 24 * 3600  # שבועיים

def _key_trade(tid: str) -> str:
    return f"{NS}:item:{tid}"

def _key_active() -> str:
    return f"{NS}:active"

# ------------- Core -------------
def create_trade(payload: Dict[str, Any]) -> str:
    tid = payload.get("id") or uuid.uuid4().hex[:12]
    payload["id"] = tid
    payload["created_ts"] = int(time.time())
    payload.setdefault("status", "TRACKED")
    if RED:
        RED.set(_key_trade(tid), json.dumps(payload, ensure_ascii=False), ex=TTL_SEC)
        RED.sadd(_key_active(), tid)
    else:
        _MEM_TRADES[tid] = payload
        _MEM_ACTIVE.add(tid)
    return tid

def get_trade(tid: str) -> Optional[Dict[str, Any]]:
    if RED:
        raw = RED.get(_key_trade(tid))
        return json.loads(raw) if raw else None
    return _MEM_TRADES.get(tid)

def update_trade(tid: str, fields: Dict[str, Any]) -> bool:
    cur = get_trade(tid)
    if not cur: return False
    cur.update(fields)
    if RED:
        RED.set(_key_trade(tid), json.dumps(cur, ensure_ascii=False), ex=TTL_SEC)
        if cur.get("status") in {"CLOSED","CANCELLED"}:
            RED.srem(_key_active(), tid)
    else:
        _MEM_TRADES[tid] = cur
        if cur.get("status") in {"CLOSED","CANCELLED"}:
            _MEM_ACTIVE.discard(tid)
    return True

def list_active() -> List[Dict[str, Any]]:
    tids: List[str] = []
    out: List[Dict[str, Any]] = []
    if RED:
        tids = list(RED.smembers(_key_active()) or [])
        tids = [t.decode() if isinstance(t, bytes) else t for t in tids]
    else:
        tids = list(_MEM_ACTIVE)

    for tid in tids:
        it = get_trade(tid)
        if it: out.append(it)
    return out

# ------------- Memory fallback -------------
_MEM_TRADES: Dict[str, Dict[str, Any]] = {}
_MEM_ACTIVE: set[str] = set()

# storage/trades_store.py
from __future__ import annotations
import json, threading, os
from typing import Optional, Dict, List
from utils.trade_state import Trade, TradeState

_REDIS_URL = os.getenv("REDIS_URL", "").strip()
_NAMESPACE = os.getenv("REDIS_NAMESPACING", "algogpt:v2").strip()
_redis = None
if _REDIS_URL:
    try:
        import redis  # type: ignore
        _redis = redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception:
        _redis = None

_mem: Dict[str, Trade] = {}
_lock = threading.Lock()


def _key(tid: str) -> str:
    return f"{_NAMESPACE}:trade:{tid}"


def save(trade: Trade) -> None:
    if _redis:
        try:
            _redis.set(_key(trade.trade_id), json.dumps(trade.to_dict()))
            return
        except Exception:
            pass
    with _lock:
        _mem[trade.trade_id] = trade


def get(trade_id: str) -> Optional[Trade]:
    if _redis:
        try:
            s = _redis.get(_key(trade_id))
            if s:
                d = json.loads(s)
                t = Trade(**{**d, "state": TradeState(d["state"])})
                return t
        except Exception:
            pass
    with _lock:
        return _mem.get(trade_id)


def list_open() -> List[Trade]:
    def _is_open(st: TradeState) -> bool:
        return st not in {TradeState.EXITED, TradeState.STOPPED, TradeState.CANCELED, TradeState.ERROR}
    out: List[Trade] = []
    if _redis:
        try:
            raise RuntimeError("scan not implemented")
        except Exception:
            pass
    with _lock:
        for t in _mem.values():
            if _is_open(t.state):
                out.append(t)
    return out


def get_all_state() -> List[Dict[str, str]]:
    """החזרת כל מצב הטריידים בפורמט JSON-מוכן"""
    out = []
    with _lock:
        for t in _mem.values():
            try:
                out.append(t.to_dict())
            except Exception:
                pass
    return out


def set_state(trade_id: str, to: TradeState) -> Optional[Trade]:
    t = get(trade_id)
    if not t:
        return None
    t.set_state(to)
    save(t)
    return t


__all__ = ["save", "get", "list_open", "set_state", "get_all_state"]


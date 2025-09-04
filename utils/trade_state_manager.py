# utils/trade_state_manager.py
from __future__ import annotations
import time
from typing import Dict, Any, Optional

# זיכרון קל (in-proc). אם יש Redis – אפשר להעביר לשם.
STATE: Dict[str, Dict[str, Any]] = {}
TTL_SEC = 60 * 60 * 24  # 24h

def _now() -> int:
    return int(time.time())

def put(trade_id: str, data: Dict[str, Any]) -> None:
    STATE[trade_id] = {**data, "_ts": _now()}

def get(trade_id: str) -> Optional[Dict[str, Any]]:
    x = STATE.get(trade_id)
    if not x:
        return None
    if _now() - int(x.get("_ts", 0)) > TTL_SEC:
        STATE.pop(trade_id, None)
        return None
    return x

def update(trade_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cur = get(trade_id)
    if not cur:
        return None
    cur.update(patch)
    cur["_ts"] = _now()
    STATE[trade_id] = cur
    return cur

def remove(trade_id: str) -> None:
    STATE.pop(trade_id, None)

def list_open() -> Dict[str, Any]:
    # החזר snapshot מהיר
    out = {}
    for k, v in list(STATE.items()):
        if _now() - int(v.get("_ts",0)) > TTL_SEC:
            STATE.pop(k, None)
            continue
        if v.get("closed"):
            continue
        out[k] = v
    return out

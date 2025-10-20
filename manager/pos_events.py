# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, json, hashlib
from contextlib import suppress
from typing import Any, Dict, Optional
import asyncio

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

_NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web")
_REDIS_URL = os.getenv("REDIS_URL", "").strip()

_POS_EVENTS_ENABLE = os.getenv("POS_EVENTS_ENABLE", "1").lower() in ("1", "true", "yes", "on")
_POS_EVENTS_KEY = os.getenv("POS_EVENTS_KEY", "pos:events")
_POS_EVENTS_CHAN = os.getenv("POS_EVENTS_CHAN", "pos:events:chan")
_POS_EVENTS_MAX = int(os.getenv("POS_EVENTS_MAX", "500") or 500)
_POS_EVENTS_EXPIRE_SEC = int(os.getenv("POS_EVENTS_EXPIRE_SEC", "86400") or 86400)

_redis = None
_redis_lock = asyncio.Lock()

async def _get_redis():
    global _redis
    if _redis and getattr(_redis, "ping", None):
        return _redis
    if not (_REDIS_URL and aioredis):
        return None
    async with _redis_lock:
        if _redis:
            return _redis
        _redis = aioredis.from_url(_REDIS_URL, decode_responses=True)
        return _redis

def _idem(event: Dict[str, Any]) -> str:
    b = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.md5(b).hexdigest()[:12]

async def emit(symbol: str, kind: str, **payload) -> None:
    """
    פרסום אירועי פוזיציה (SL-move/TP1/TP2/TP3/TP_hit/BE וכו') לרדיס:
      * רשימת לוג: LPUSH/LTRIM על POS_EVENTS_KEY
      * PUBSUB: PUBLISH ל־POS_EVENTS_CHAN
    """
    if not _POS_EVENTS_ENABLE:
        return
    r = await _get_redis()
    if not r:
        return
    evt = {
        "ts": time.time(),
        "ns": _NS,
        "symbol": (symbol or "").upper(),
        "type": str(kind),
        "data": payload or {},
    }
    evt["idem"] = _idem(evt)
    raw = json.dumps(evt, ensure_ascii=False, separators=(",", ":"))
    try:
        pipe = r.pipeline()
        pipe.lpush(_POS_EVENTS_KEY, raw)
        pipe.ltrim(_POS_EVENTS_KEY, 0, max(0, _POS_EVENTS_MAX - 1))
        if _POS_EVENTS_EXPIRE_SEC > 0:
            pipe.expire(_POS_EVENTS_KEY, _POS_EVENTS_EXPIRE_SEC)
        pipe.publish(_POS_EVENTS_CHAN, raw)
        await pipe.execute()
    except Exception:
        # לא להפיל את הזרימה על טלמטריה
        pass

# קיצורי דרך נוחים
async def emit_sl_move(symbol: str, price_from: float, price_to: float, *, source: str = "manager",
                       reason: Optional[str] = None, order_id: Optional[str] = None,
                       mode: Optional[str] = None) -> None:
    await emit(symbol, "sl_move",
               frm=float(price_from), to=float(price_to),
               source=source, reason=reason, order_id=order_id, mode=mode)

async def emit_tp_hit(symbol: str, tp_index: int, price: float, filled_qty: float, *, order_id: Optional[str] = None) -> None:
    await emit(symbol, f"tp{int(tp_index)}_hit", price=float(price), filled_qty=float(filled_qty), order_id=order_id)

async def emit_be_move(symbol: str, price_to: float, *, price_from: Optional[float] = None, reason: str = "BE_guard") -> None:
    await emit(symbol, "be_move", to=float(price_to), frm=(float(price_from) if price_from is not None else None), reason=reason)

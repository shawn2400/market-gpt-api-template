# utils/pos_events.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, time, asyncio
from typing import Any, Dict, Optional, Sequence

from utils.redis_helper import get_redis

_POS_EVENTS_ENABLE = os.getenv("POS_EVENTS_ENABLE", "1").lower() in ("1","true","yes","on")
_POS_EVENTS_KEY = os.getenv("POS_EVENTS_KEY", "pos:events")
_POS_EVENTS_CHAN = os.getenv("POS_EVENTS_CHAN", "pos:events:chan")
_POS_EVENTS_MAX = int(os.getenv("POS_EVENTS_MAX", "500"))          # כמה לשמור ברשימה
_POS_EVENTS_EXPIRE_SEC = int(os.getenv("POS_EVENTS_EXPIRE_SEC", "86400"))  # שמירת יום

def _now_ts() -> int:
    return int(time.time())

async def push_event(event: Dict[str, Any]) -> None:
    """
    Push + Publish אירוע בזמן אמת:
      - LPUSH לרשימה (עם LTRIM לקאפ)
      - PUBLISH לערוץ PUBSUB
    event דוגמה: {"sym":"BTCUSDT","op":"trail_move","from":68000.5,"to":68120.1,"ts":...}
    """
    if not _POS_EVENTS_ENABLE:
        return
    r = await get_redis()
    if not r:
        return
    ev = dict(event)
    ev.setdefault("ts", _now_ts())
    raw = json.dumps(ev, ensure_ascii=False, separators=(",",":"))
    # BACKLOG (LIST)
    await r.lpush(_POS_EVENTS_KEY, raw)
    await r.ltrim(_POS_EVENTS_KEY, 0, _POS_EVENTS_MAX - 1)
    # TTL לרשימה
    await r.expire(_POS_EVENTS_KEY, _POS_EVENTS_EXPIRE_SEC)
    # PUBSUB
    await r.publish(_POS_EVENTS_CHAN, raw)

# ===================== קיצורי דרך “נוחים” =====================

async def trail_move(sym: str, from_price: float, to_price: float, **kw: Any) -> None:
    await push_event({"sym": sym, "op": "trail_move", "from": float(from_price), "to": float(to_price), **kw})

async def be_arm(sym: str, at_bps: float, **kw: Any) -> None:
    await push_event({"sym": sym, "op": "be_arm", "bps": float(at_bps), **kw})

async def be_move(sym: str, from_bps: float, to_bps: float, **kw: Any) -> None:
    await push_event({"sym": sym, "op": "be_move", "from_bps": float(from_bps), "to_bps": float(to_bps), **kw})

async def sl_move(sym: str, from_price: float, to_price: float, **kw: Any) -> None:
    await push_event({"sym": sym, "op": "sl_move", "from": float(from_price), "to": float(to_price), **kw})

async def tp_place(sym: str, price: float, qty: float, idx: int = 0, **kw: Any) -> None:
    await push_event({"sym": sym, "op": "tp_place", "price": float(price), "qty": float(qty), "idx": int(idx), **kw})

async def tp_hit(sym: str, price: float, qty: float, idx: Optional[int] = None, **kw: Any) -> None:
    data = {"sym": sym, "op": "tp_hit", "price": float(price), "qty": float(qty)}
    if idx is not None: data["idx"] = int(idx)
    await push_event({**data, **kw})

async def note(sym: str, msg: str, level: str = "info", **kw: Any) -> None:
    await push_event({"sym": sym, "op": "note", "msg": str(msg), "level": level, **kw})

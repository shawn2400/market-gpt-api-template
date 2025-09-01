# utils/runtime_prefs.py
from __future__ import annotations
import json
import time
from typing import Any, Dict, List, Optional, Set

from .redis_client import get_redis


class TelePrefs:
    """
    העדפות טלגרם "דל-עומס" ב-Redis.

    keyspace:
      tprefs:{chat}:pin_summary         -> "on"/"off"
      tprefs:{chat}:pin_message_id      -> int
      tprefs:{chat}:bundle_window       -> int seconds
      bundle:{chat}                     -> list of JSON (LPUSH/RPOP)
      snooze:trade:{trade_id}           -> "1" (TTL)
      snooze:symbol:{symbol}            -> "1" (TTL)
      watchdog:last_beat                -> ts (float)
      watchdog:bundle_stats:{chat}      -> hash {"queued":int, "last_flush":ts}
      tprefs:pin_chats                  -> SET of chat_ids שבהם pin_summary=on
    """

    def __init__(self) -> None:
        # מצופה ש-get_redis() מחזיר redis.asyncio.Redis עם decode_responses=True
        self.r = get_redis()

    # ---------- Pin Summary ----------
    async def set_pin_summary(self, chat_id: int, on: bool) -> None:
        await self.r.set(f"tprefs:{chat_id}:pin_summary", "on" if on else "off")
        if on:
            await self.r.sadd("tprefs:pin_chats", int(chat_id))
        else:
            await self.r.srem("tprefs:pin_chats", int(chat_id))

    async def is_pin_summary(self, chat_id: int) -> bool:
        return (await self.r.get(f"tprefs:{chat_id}:pin_summary")) == "on"

    async def set_pin_message_id(self, chat_id: int, message_id: Optional[int]) -> None:
        key = f"tprefs:{chat_id}:pin_message_id"
        if message_id is None:
            await self.r.delete(key)
        else:
            await self.r.set(key, int(message_id))

    async def get_pin_message_id(self, chat_id: int) -> Optional[int]:
        v = await self.r.get(f"tprefs:{chat_id}:pin_message_id")
        return int(v) if v is not None else None

    async def list_pin_chats(self) -> Set[int]:
        members = await self.r.smembers("tprefs:pin_chats")
        out: Set[int] = set()
        for m in members or []:
            try:
                out.add(int(m))
            except Exception:
                pass
        return out

    # ---------- Bundling ----------
    async def set_bundle_window(self, chat_id: int, seconds: int) -> None:
        await self.r.set(f"tprefs:{chat_id}:bundle_window", max(0, int(seconds)))

    async def get_bundle_window(self, chat_id: int) -> int:
        v = await self.r.get(f"tprefs:{chat_id}:bundle_window")
        return int(v) if v is not None else 0

    async def bundle_enqueue(self, chat_id: int, event: Dict[str, Any]) -> None:
        key = f"bundle:{chat_id}"
        await self.r.lpush(key, json.dumps(event))
        await self.r.hincrby(f"watchdog:bundle_stats:{chat_id}", "queued", 1)

    async def bundle_flush(self, chat_id: int, max_items: int = 200) -> List[Dict[str, Any]]:
        key = f"bundle:{chat_id}"
        out: List[Dict[str, Any]] = []
        for _ in range(max_items):
            raw = await self.r.rpop(key)
            if raw is None:
                break
            try:
                out.append(json.loads(raw))
            except Exception:
                # בליעת אירוע פגום
                pass
        await self.r.hset(f"watchdog:bundle_stats:{chat_id}", mapping={"last_flush": time.time()})
        return out

    # ---------- Snooze ----------
    async def snooze_trade(self, trade_id: str, minutes: int) -> None:
        await self.r.set(f"snooze:trade:{trade_id}", "1", ex=max(1, int(minutes)) * 60)

    async def snooze_symbol(self, symbol: str, minutes: int) -> None:
        await self.r.set(f"snooze:symbol:{symbol.upper()}", "1", ex=max(1, int(minutes)) * 60)

    async def is_snoozed_trade(self, trade_id: str) -> bool:
        return (await self.r.exists(f"snooze:trade:{trade_id}")) == 1

    async def is_snoozed_symbol(self, symbol: str) -> bool:
        return (await self.r.exists(f"snooze:symbol:{symbol.upper()}")) == 1

    # ---------- Watchdog beat ----------
    async def set_watchdog_beat(self) -> None:
        await self.r.set("watchdog:last_beat", time.time())

    async def get_watchdog_beat(self) -> Optional[float]:
        v = await self.r.get("watchdog:last_beat")
        return float(v) if v else None




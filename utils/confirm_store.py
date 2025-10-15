
# utils/confirm_store.py
from __future__ import annotations
import os, time, secrets, json
from typing import Any, Dict, List, Optional
from contextlib import suppress

# Optional Redis backend (async)
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

REDIS_URL = (os.getenv("REDIS_URL") or os.getenv("ALGOGPT_REDIS_URL") or "").strip()
NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"

class ConfirmStore:
    """
    Unified ConfirmStore with Redis-first (if available) and in-memory fallback.
    API:
      - create(req: Dict[str,Any]) -> str
      - decide(ticket_id: str, approved: bool) -> Dict[str,Any]
      - pending() -> List[Dict[str,Any]]
      - remove(ticket_id: str) -> None
    """
    _mem_items: Dict[str, Dict[str, Any]] = {}
    _redis = None

    @classmethod
    async def _get_redis(cls):
        if not (aioredis and REDIS_URL):
            return None
        if cls._redis:
            return cls._redis
        cls._redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        return cls._redis

    @staticmethod
    def _mem_create(req: Dict[str, Any]) -> str:
        tid = str(req.get("ticket_id") or f"T_{int(time.time())}_{secrets.token_hex(4)}")
        ConfirmStore._mem_items[tid] = {"ticket_id": tid, "req": dict(req), "ts": time.time(), "approved": None}
        return tid

    @staticmethod
    def _mem_decide(ticket_id: str, approved: bool) -> Dict[str, Any]:
        it = ConfirmStore._mem_items.get(str(ticket_id))
        if not it:
            raise RuntimeError("ticket_not_found")
        it["approved"] = bool(approved)
        return dict(it)

    @staticmethod
    def _mem_pending() -> List[Dict[str, Any]]:
        return [v for v in ConfirmStore._mem_items.values() if v.get("approved") is None]

    @staticmethod
    def _mem_remove(ticket_id: str) -> None:
        ConfirmStore._mem_items.pop(str(ticket_id), None)

    # ---- public API ----

    @classmethod
    async def create(cls, req: Dict[str, Any]) -> str:
        # Try Redis
        r = await cls._get_redis()
        tid = str(req.get("ticket_id") or f"T_{int(time.time())}_{secrets.token_hex(4)}")
        rec = {"ticket_id": tid, "req": dict(req), "ts": time.time(), "approved": None}
        if r:
            key = f"{NS}:confirm:{tid}"
            # TTL can be controlled by OPS_TICKET_TTL_SEC if set on caller
            ttl = int(os.getenv("OPS_TICKET_TTL_SEC", "1800") or 1800)
            await r.setex(key, ttl, json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
            # index for pending scan
            await r.sadd(f"{NS}:confirm:index", tid)
            return tid
        # Fallback to memory
        return cls._mem_create(req)

    @classmethod
    async def decide(cls, ticket_id: str, approved: bool) -> Dict[str, Any]:
        r = await cls._get_redis()
        if r:
            key = f"{NS}:confirm:{ticket_id}"
            raw = await r.get(key)
            if not raw:
                # may be already expired/memory fallback
                return cls._mem_decide(ticket_id, approved)
            obj = json.loads(raw)
            obj["approved"] = bool(approved)
            # preserve TTL if possible
            try:
                await r.set(key, json.dumps(obj, ensure_ascii=False, separators=(",", ":")), keepttl=True)
            except TypeError:
                # fallback: fetch remaining TTL and setex
                ttl = await r.ttl(key)
                if ttl and ttl > 0:
                    await r.setex(key, ttl, json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
                else:
                    await r.set(key, json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
            with suppress(Exception):
                await r.srem(f"{NS}:confirm:index", ticket_id)
            return obj
        return cls._mem_decide(ticket_id, approved)

    @classmethod
    async def pending(cls) -> List[Dict[str, Any]]:
        r = await cls._get_redis()
        if r:
            tids: List[str] = []
            with suppress(Exception):
                tids = list(await r.smembers(f"{NS}:confirm:index")) or []
            out: Dict[str, Dict[str, Any]] = {}
            for tid in tids:
                raw = await r.get(f"{NS}:confirm:{tid}")
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                if obj.get("approved") is None:
                    out[obj.get("ticket_id") or tid] = obj
            # also include mem pending (dev/local)
            for it in cls._mem_pending():
                if isinstance(it, dict) and it.get("approved") is None:
                    out[it.get("ticket_id")] = it  # type: ignore[index]
            # normalize: return list of dicts with keys {ticket_id, req, ts, approved}
            return list(out.values())
        return cls._mem_pending()

    @classmethod
    async def remove(cls, ticket_id: str) -> None:
        r = await cls._get_redis()
        if r:
            with suppress(Exception):
                await r.delete(f"{NS}:confirm:{ticket_id}")
            with suppress(Exception):
                await r.srem(f"{NS}:confirm:index", ticket_id)
        cls._mem_remove(ticket_id)



# utils/mode_store.py
from __future__ import annotations
import os, json, time
from typing import Optional
try:
    import redis  # type: ignore
except Exception:
    redis = None

REDIS_URL = os.getenv("REDIS_URL", "")
KEY = "algogpt:exec_mode"   # "dry" | "live"

class ExecMode:
    _mem = {"value": "dry", "ts": time.time()}
    _r = redis.Redis.from_url(REDIS_URL, decode_responses=True) if (redis and REDIS_URL) else None

    @classmethod
    def get(cls) -> str:
        if cls._r:
            v = cls._r.get(KEY)
            if v in ("dry","live"): return v
        return cls._mem["value"]

    @classmethod
    def set(cls, val: str) -> None:
        val = "live" if str(val).lower().strip() == "live" else "dry"
        cls._mem = {"value": val, "ts": time.time()}
        if cls._r:
            cls._r.set(KEY, val, ex=86400)

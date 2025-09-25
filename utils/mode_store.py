# utils/mode_store.py
from __future__ import annotations
import os, time
try:
    import redis  # type: ignore
except Exception:
    redis = None

REDIS_URL = os.getenv("REDIS_URL", "")
KEY = "algogpt:exec_mode"   # "dry" | "live"

class ExecMode:
    _mem = {"value": os.getenv("DEFAULT_EXEC_MODE", "dry").lower() in ("live","1","true","on") and "live" or "dry",
            "ts": time.time()}
    _r = None
    if redis and REDIS_URL:
        try:
            _r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        except Exception:
            _r = None

    @classmethod
    def get(cls) -> str:
        if cls._r:
            v = cls._r.get(KEY)
            if v in ("dry","live"):
                return v
        return cls._mem["value"]

    @classmethod
    def set(cls, val: str) -> None:
        val = "live" if str(val).lower().strip() == "live" else "dry"
        cls._mem = {"value": val, "ts": time.time()}
        if cls._r:
            try:
                cls._r.set(KEY, val, ex=86400)
            except Exception:
                pass



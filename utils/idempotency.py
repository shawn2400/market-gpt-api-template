# utils/idempotency.py
from __future__ import annotations
import os, time, json, hashlib, logging
from typing import Optional, Dict, Any, Tuple
try:
    from utils.redis_client import get_redis
except Exception:
    get_redis = lambda: None  # type: ignore

log = logging.getLogger("algogpt.idem")

DEFAULT_TTL_SEC = int(os.getenv("IDEMPOTENCY_WEBHOOK_TTL_SEC", "30"))

_mem: Dict[str, float] = {}

def _digest_key(parts: Tuple[Any, ...]) -> str:
    raw = json.dumps(parts, separators=(",", ":"), sort_keys=True, default=str)
    return "idem:wh:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

async def check_and_set(parts: Tuple[Any, ...], ttl_sec: int = DEFAULT_TTL_SEC) -> bool:
    """
    מחזיר True אם זו הפעם הראשונה (שמנו key), אחרת False (כפילות).
    """
    key = _digest_key(parts)
    r = None
    try:
        r = get_redis()
    except Exception:
        r = None

    now = time.time()
    if r:
        try:
            ok = r.set(key, str(int(now)), nx=True, ex=max(1, ttl_sec))
            return bool(ok)
        except Exception as e:
            log.warning("idempotency.redis_error: %s", e)

    # Memory fallback
    ts = _mem.get(key, 0.0)
    if now - ts < ttl_sec:
        return False
    _mem[key] = now
    # ניקוי עדין
    for k, v in list(_mem.items()):
        if now - v > max(2 * ttl_sec, 120):
            _mem.pop(k, None)
    return True

async def idem_for_request(body: bytes, headers: Dict[str, str], extra: Optional[Dict[str, Any]] = None, ttl_sec: int = DEFAULT_TTL_SEC) -> bool:
    sig = headers.get("x-signature") or headers.get("X-Signature") or headers.get("X-Hub-Signature-256") or ""
    ts  = headers.get("X-Signature-Timestamp") or headers.get("x-signature-timestamp") or ""
    auth= headers.get("Authorization") or headers.get("authorization") or ""
    parts = (sig, ts, auth[:64], hashlib.sha256(body).hexdigest(), json.dumps(extra or {}, sort_keys=True))
    return await check_and_set(parts, ttl_sec=ttl_sec)

__all__ = ["check_and_set", "idem_for_request", "DEFAULT_TTL_SEC"]




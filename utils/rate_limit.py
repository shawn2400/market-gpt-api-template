# utils/rate_limit.py
from __future__ import annotations
import os, time, asyncio
from typing import Tuple, Optional, Callable
from fastapi import Request, HTTPException

# ננסה Redis אסינכרוני; אם אין/נכשל – נשתמש בזיכרון
try:
    from redis.asyncio import Redis  # redis==5 כולל asyncio
except Exception:
    Redis = None  # type: ignore

_REDIS_URL = os.getenv("REDIS_URL", "").strip()
_REDIS: Optional["Redis"] = None
if Redis and _REDIS_URL:
    try:
        _REDIS = Redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception:
        _REDIS = None

# ===== In-memory fallback (פר-פרוסס) =====
_mem_lock = asyncio.Lock()
_mem_state: dict[str, Tuple[float, float]] = {}  # key -> (tokens, ts)

def _now() -> float:
    return time.time()

async def _bucket_take_redis(key: str, rpm: int, burst_factor: float) -> Tuple[bool, float]:
    """
    Token-bucket ב-Redis: שומר HSET עם fields: tokens, ts
    מחזיר (allowed, retry_after_seconds)
    """
    assert _REDIS is not None
    capacity = max(1.0, float(rpm) * float(burst_factor))
    refill_per_sec = float(rpm) / 60.0
    ts = _now()

    # נטען מצב קיים
    h = await _REDIS.hgetall(key) or {}
    tokens = float(h.get("tokens") or capacity)
    last_ts = float(h.get("ts") or ts)

    # מילוי מחדש לפי זמן שחלף
    elapsed = max(0.0, ts - last_ts)
    tokens = min(capacity, tokens + elapsed * refill_per_sec)

    allowed = tokens >= 1.0
    if allowed:
        tokens -= 1.0
        retry_after = 0.0
    else:
        # כמה זמן עד שיצטבר טוקן
        need = 1.0 - tokens
        retry_after = max(0.0, need / refill_per_sec)

    pipe = _REDIS.pipeline(transaction=False)
    pipe.hset(key, mapping={"tokens": tokens, "ts": ts})
    pipe.expire(key, max(120, int(2 * 60)))  # TTL הגנתי
    await pipe.execute()

    return allowed, retry_after

async def _bucket_take_mem(key: str, rpm: int, burst_factor: float) -> Tuple[bool, float]:
    capacity = max(1.0, float(rpm) * float(burst_factor))
    refill_per_sec = float(rpm) / 60.0
    ts = _now()

    async with _mem_lock:
        tokens, last_ts = _mem_state.get(key, (capacity, ts))
        elapsed = max(0.0, ts - last_ts)
        tokens = min(capacity, tokens + elapsed * refill_per_sec)

        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0
            retry_after = 0.0
        else:
            need = 1.0 - tokens
            retry_after = max(0.0, need / refill_per_sec)

        _mem_state[key] = (tokens, ts)

    return allowed, retry_after

async def take(bucket: str, identity: str, rpm: int, burst_factor: float = 1.0) -> Tuple[bool, float]:
    if rpm <= 0:
        return True, 0.0
    key = f"rl:{bucket}:{identity}"
    if _REDIS is not None:
        try:
            return await _bucket_take_redis(key, rpm, burst_factor)
        except Exception:
            # נפל Redis → נגלוש לזיכרון
            pass
    return await _bucket_take_mem(key, rpm, burst_factor)

def _client_identity(request: Request, by: str) -> str:
    """
    by: "ip" | "token" | "token_or_ip"
    """
    if by == "ip":
        xfwd = request.headers.get("x-forwarded-for")
        if xfwd:
            return xfwd.split(",")[0].strip()
        return (request.client.host if request.client else "unknown")
    auth = (request.headers.get("authorization") or "").strip()
    api_key = (request.headers.get("x-api-key") or "").strip()
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if by == "token" and token:
        return f"t:{token}"
    if by == "token" and api_key:
        return f"k:{api_key}"
    if by == "token_or_ip":
        if token:
            return f"t:{token}"
        if api_key:
            return f"k:{api_key}"
        return _client_identity(request, "ip")
    return _client_identity(request, "ip")

def require(bucket: str, rpm_env_or_int: int | str = "AI_ANALYZE_RPM", *, burst: float = 1.0, by: str = "token_or_ip") -> Callable:
    """
    שימוש: dependencies=[Depends(rate_limit.require("ai_analyze", "AI_ANALYZE_RPM", burst=1.3))]
    """
    async def _dep(request: Request):
        # שליפת RPM מה-ENV אם התקבל מחרוזת
        if isinstance(rpm_env_or_int, str):
            raw = os.getenv(rpm_env_or_int, "5")
            try:
                rpm = int(raw)
            except Exception:
                rpm = 5
        else:
            rpm = int(rpm_env_or_int)

        identity = _client_identity(request, by)
        allowed, retry_after = await take(bucket, identity, rpm, burst)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(int(retry_after + 0.5))},
            )
    return _dep





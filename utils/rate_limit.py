# utils/rate_limit.py
from __future__ import annotations

import os, time, asyncio, random
from typing import Optional, Tuple
from fastapi import Request, HTTPException

# ================= Env =================
REDIS_URL      = os.getenv("REDIS_URL", "").strip()
REDIS_PREFIX   = os.getenv("REDIS_NAMESPACING", "algogpt:v2").strip() or "algogpt:v2"
_AI_RPM_DEF    = int(os.getenv("AI_ANALYZE_RPM", "5"))

# ================= Redis (optional) =================
try:
    import redis  # type: ignore
    _RED = redis.from_url(
        REDIS_URL, decode_responses=True,
        socket_timeout=2.5, retry_on_timeout=True,
    ) if REDIS_URL else None
except Exception:
    _RED = None

# ================= In-Memory Fallback =================
_mem_store: dict[str, dict[str, float]] = {}
_mem_lock = asyncio.Lock()

def _extract_token_or_ip(req: Request, *, by_token_only: bool) -> str:
    tok = None
    auth = req.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        tok = auth.split(" ", 1)[1].strip()
    tok = tok or req.headers.get("X-API-Key") or req.headers.get("X-Api-Key")
    if by_token_only and not tok:
        raise HTTPException(401, "Missing API token for rate limit scope")
    if tok:
        return f"tok:{tok[:32]}"
    ip = (req.client.host if req.client else "0.0.0.0")
    return f"ip:{ip}"

def _refill(tokens: float, last_ts: float, rpm: int) -> Tuple[float, float]:
    now = time.time()
    rate = max(0.0, float(rpm) / 60.0)     # tokens/sec
    new_tokens = min(float(rpm), tokens + (now - last_ts) * rate)
    return new_tokens, now

async def _allow_mem(ns: str, ident: str, rpm: int, burst: int) -> bool:
    key = f"{ns}:{ident}"
    async with _mem_lock:
        rec = _mem_store.get(key, {"tok": float(burst), "ts": time.time()})
        tok, ts = float(rec["tok"]), float(rec["ts"])
        tok, now = _refill(tok, ts, rpm)
        allowed = tok >= 1.0
        if allowed:
            tok -= 1.0
        _mem_store[key] = {"tok": tok, "ts": now}
        return allowed

# ================= Redis Lua (atomic token bucket) =================
# KEYS[1] = key, ARGV = [rpm, burst, now, ttl_seconds]
# returns 1 if allowed, 0 otherwise
_REDIS_LUA = """
local key   = KEYS[1]
local rpm   = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now   = tonumber(ARGV[3])
local ttl   = tonumber(ARGV[4])

local rec = redis.call('HMGET', key, 'tok', 'ts')
local tok = tonumber(rec[1])
local ts  = tonumber(rec[2])

if tok == nil then
  tok = burst
  ts  = now
end

local rate = rpm / 60.0
local elapsed = now - ts
if elapsed < 0 then elapsed = 0 end
tok = math.min(burst, tok + elapsed * rate)

local allowed = 0
if tok >= 1.0 then
  tok = tok - 1.0
  allowed = 1
end

redis.call('HMSET', key, 'tok', tok, 'ts', now)
-- TTL מעט מעל דקה, עם jitter קטן כדי למנוע thundering herd
redis.call('EXPIRE', key, math.max(ttl, 60) + math.random(0,5))
return allowed
"""

if _RED:
    try:
        _RL_SCRIPT = _RED.register_script(_REDIS_LUA)
    except Exception:
        _RL_SCRIPT = None
else:
    _RL_SCRIPT = None

def _allow_redis(ns: str, ident: str, rpm: int, burst: int) -> bool:
    if not (_RED and _RL_SCRIPT):
        return False
    key = f"{REDIS_PREFIX}:rl:{ns}:{ident}"
    try:
        now = time.time()
        ttl = 120  # בסיסי; בפועל EXPIRE יקבל גם jitter קטן בתוך הסקריפט
        res = _RL_SCRIPT(keys=[key], args=[rpm, burst, now, ttl])
        return bool(int(res or 0) == 1)
    except Exception:
        return False

# ================= Public Dependency =================
def require_rate_limit(
    ns: str = "ai_analyze",
    *,
    rpm: Optional[int] = None,
    burst: Optional[int] = None,
    by_token_only: bool = False,
):
    """
    FastAPI dependency:
      - ns: namespace של ה־bucket (מומלץ ייחודי לכל ראוטר)
      - rpm: קצב לדקה
      - burst: מקסימום טוקנים בבאגט (ברירת מחדל = rpm)
      - by_token_only: אם True מזהה לפי טוקן בלבד (דורש Authorization/X-API-Key)
    """
    _rpm = int(rpm or _AI_RPM_DEF)
    _burst = int(burst or _rpm)
    if _rpm <= 0:  # השבתה רכה
        async def _dep_disabled(_: Request): return True
        return _dep_disabled

    async def _dep(req: Request):
        ident = _extract_token_or_ip(req, by_token_only=by_token_only)
        ok = _allow_redis(ns, ident, _rpm, _burst) if _RED else await _allow_mem(ns, ident, _rpm, _burst)
        if not ok:
            raise HTTPException(429, f"Rate limit exceeded ({_rpm}/min)")
        return True

    return _dep








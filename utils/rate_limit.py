# utils/rate_limit.py
from __future__ import annotations
import os, time, asyncio
from typing import Optional, Tuple
from fastapi import Request, HTTPException

REDIS_URL = os.getenv("REDIS_URL", "").strip()
REDIS_PREFIX = os.getenv("REDIS_NAMESPACING", "algogpt:v2")
try:
    import redis  # type: ignore
    _RED = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None
except Exception:
    _RED = None

_AI_RPM_DEFAULT = int(os.getenv("AI_ANALYZE_RPM", "5"))

_mem_store = {}
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
        return f"tok:{tok[:16]}"
    ip = (req.client.host if req.client else "0.0.0.0")
    return f"ip:{ip}"

def _refill(tokens: float, last_ts: float, rpm: int) -> Tuple[float, float]:
    now = time.time()
    rate = max(0.0, float(rpm) / 60.0)
    new_tokens = min(float(rpm), tokens + (now - last_ts) * rate)
    return new_tokens, now

async def _allow_mem(ns: str, ident: str, rpm: int, burst: int) -> bool:
    key = f"{ns}:{ident}"
    async with _mem_lock:
        rec = _mem_store.get(key, {"tok": float(burst), "ts": time.time()})
        tok, ts = float(rec["tok"]), float(rec["ts"])
        tok, now = _refill(tok, ts, rpm)
        if tok >= 1.0:
            tok -= 1.0
            _mem_store[key] = {"tok": tok, "ts": now}
            return True
        _mem_store[key] = {"tok": tok, "ts": now}
        return False

def _allow_redis(ns: str, ident: str, rpm: int, burst: int) -> bool:
    if not _RED:
        return False
    key = f"{REDIS_PREFIX}:rl:{ns}:{ident}"
    pipe = _RED.pipeline()
    pipe.hget(key, "tok")
    pipe.hget(key, "ts")
    tok_s, ts_s = pipe.execute()
    try:
        tok = float(tok_s) if tok_s is not None else float(burst)
        ts = float(ts_s) if ts_s is not None else time.time()
    except Exception:
        tok, ts = float(burst), time.time()
    tok, now = _refill(tok, ts, rpm)
    allowed = tok >= 1.0
    if allowed:
        tok -= 1.0
    _RED.hset(key, mapping={"tok": tok, "ts": now})
    _RED.expire(key, max(60, int(2 * 60)))
    return allowed

def require_rate_limit(ns: str = "ai_analyze", *, rpm: Optional[int] = None,
                       burst: Optional[int] = None, by_token_only: bool = False):
    _rpm = int(rpm or _AI_RPM_DEFAULT)
    _burst = int(burst or _rpm)
    async def _dep(req: Request):
        ident = _extract_token_or_ip(req, by_token_only=by_token_only)
        ok = _allow_redis(ns, ident, _rpm, _burst) if _RED else await _allow_mem(ns, ident, _rpm, _burst)
        if not ok:
            raise HTTPException(429, f"Rate limit exceeded ({_rpm}/min)")
        return True
    return _dep






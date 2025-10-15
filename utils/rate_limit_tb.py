# utils/rate_limit_tb.py
from __future__ import annotations
import os, re, json, time, hashlib, logging, asyncio
from typing import Any, Dict, Optional, Tuple, List

logger = logging.getLogger("algogpt.tb")

# ==== ENV ====
TB_ENABLE              = os.getenv("TB_ENABLE", "0").lower() in ("1","true","yes","on")
TB_NAMESPACE           = os.getenv("TB_NAMESPACE", "tb").strip() or "tb"

TB_DEFAULT_RATE        = float(os.getenv("TB_DEFAULT_RATE", "5"))
TB_DEFAULT_BURST       = float(os.getenv("TB_DEFAULT_BURST", "15"))
TB_DEFAULT_PERIOD_SEC  = float(os.getenv("TB_DEFAULT_PERIOD_SEC", "1"))

TB_REST_RATE           = float(os.getenv("TB_REST_RATE", os.getenv("TB_DEFAULT_RATE", "5")))
TB_REST_BURST          = float(os.getenv("TB_REST_BURST", os.getenv("TB_DEFAULT_BURST", "15")))
TB_REST_PERIOD_SEC     = float(os.getenv("TB_REST_PERIOD_SEC", os.getenv("TB_DEFAULT_PERIOD_SEC", "1")))

TB_WEB_RATE            = float(os.getenv("TB_WEB_RATE", os.getenv("TB_DEFAULT_RATE", "2")))
TB_WEB_BURST           = float(os.getenv("TB_WEB_BURST", os.getenv("TB_DEFAULT_BURST", "6")))
TB_WEB_PERIOD_SEC      = float(os.getenv("TB_WEB_PERIOD_SEC", os.getenv("TB_DEFAULT_PERIOD_SEC", "1")))

TB_SSE_RATE            = float(os.getenv("TB_SSE_RATE", "20"))
TB_SSE_BURST           = float(os.getenv("TB_SSE_BURST", "20"))
TB_SSE_PERIOD_SEC      = float(os.getenv("TB_SSE_PERIOD_SEC", "60"))

REDIS_URL = (os.getenv("REDIS_URL") or os.getenv("ALGOGPT_REDIS_URL") or "").strip()

# ==== Path rules (אופציונלי, JSON של רשימת אובייקטים) ====
# [{"pattern":"^/scan/public-topk/web$","rate":1,"burst":3,"period_sec":1}, ...]
_raw_rules = os.getenv("TB_PATH_RULES", "").strip()
_PATH_RULES: List[Tuple[re.Pattern, float, float, float]] = []
if _raw_rules:
    try:
        for rule in json.loads(_raw_rules):
            _PATH_RULES.append((
                re.compile(str(rule["pattern"])),
                float(rule.get("rate", TB_DEFAULT_RATE)),
                float(rule.get("burst", TB_DEFAULT_BURST)),
                float(rule.get("period_sec", TB_DEFAULT_PERIOD_SEC)),
            ))
    except Exception as e:
        logger.warning("TB_PATH_RULES parse failed: %s", e)

# ==== Redis (async) ====
_aioredis = None
try:
    import redis.asyncio as _aioredis  # type: ignore
except Exception:
    _aioredis = None

_redis_client = None
_client_lock = asyncio.Lock()

async def _get_redis():
    global _redis_client
    if not (_aioredis and REDIS_URL):
        return None
    if _redis_client:
        return _redis_client
    async with _client_lock:
        if _redis_client:
            return _redis_client
        try:
            _redis_client = _aioredis.from_url(
                REDIS_URL, decode_responses=True, health_check_interval=15
            )
        except Exception as e:
            logger.warning("tb: redis connect failed: %s", e)
            _redis_client = None
    return _redis_client

# ==== Lua script — token bucket אטומי ====
# שומר state ב-HASH: fields {tokens, ts}
_LUA = """
local key        = KEYS[1]
local now        = tonumber(ARGV[1])
local rate       = tonumber(ARGV[2])
local capacity   = tonumber(ARGV[3])
local period_sec = tonumber(ARGV[4])

local data   = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts     = tonumber(data[2])

if tokens == nil or ts == nil then
  tokens = capacity
  ts     = now
end

local delta = now - ts
if delta < 0 then delta = 0 end
local add = delta * (rate / period_sec)
tokens = math.min(capacity, tokens + add)

local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
local ttl = math.max(period_sec * 2, 60)
redis.call('EXPIRE', key, ttl)

return {allowed, tokens}
"""

_script_sha: Optional[str] = None
_sha_lock = asyncio.Lock()

async def _load_script(r) -> str:
    global _script_sha
    if _script_sha:
        return _script_sha
    async with _sha_lock:
        if _script_sha:
            return _script_sha
        try:
            _script_sha = await r.script_load(_LUA)
        except Exception:
            # fallback: eval full script
            _script_sha = ""
    return _script_sha or ""

def _scope_for_path(path: str, sse_hint: bool=False) -> str:
    if sse_hint:
        return "SSE"
    if path.endswith("/web"):
        return "WEB"
    return "REST"

def _limits_for(path: str, scope: str) -> Tuple[float,float,float]:
    # path rules first
    for rx, rate, burst, per in _PATH_RULES:
        if rx.search(path):
            return rate, burst, per
    # class defaults
    if scope == "WEB":
        return TB_WEB_RATE, TB_WEB_BURST, TB_WEB_PERIOD_SEC
    if scope == "SSE":
        return TB_SSE_RATE, TB_SSE_BURST, TB_SSE_PERIOD_SEC
    # REST
    return TB_REST_RATE, TB_REST_BURST, TB_REST_PERIOD_SEC

def _bucket_key(ip: str, path: str, scope: str) -> str:
    ph = hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]
    return f"{TB_NAMESPACE}:bucket:{scope}:{ip}:{ph}"

async def tb_allow(ip: str, path: str, sse_hint: bool=False) -> Tuple[bool, Optional[int]]:
    """
    Returns (allowed, retry_after_sec_if_denied)
    """
    if not TB_ENABLE:
        return True, None
    r = await _get_redis()
    if not r:
        # אם אין Redis — fail-OPEN כדי לא להפיל שירות (אתה כבר מוגן ע"י RL הקל שלך)
        return True, None

    scope = _scope_for_path(path, sse_hint=sse_hint)
    rate, burst, period = _limits_for(path, scope)

    key = _bucket_key(ip or "0.0.0.0", path, scope)
    now = time.time()

    # העדפה ל-EVALSHA; נפילה ל-EVAL מלאה
    sha = await _load_script(r)
    try:
        res = await r.evalsha(sha, 1, key, now, rate, burst, period)
    except Exception:
        res = await r.eval(_LUA, 1, key, now, rate, burst, period)

    try:
        allowed = int(res[0]) == 1
        tokens  = float(res[1])
    except Exception:
        # אם משהו מוזר — אל תחנוק
        return True, None

    if allowed:
        return True, None

    # חישוב "retry-after" מקורב
    # משתנה tokens אחרי עדכון; אם <1 — זמן למלא טוקן אחד:
    # t = (1 - tokens) / (rate/period)
    fill_rate = rate / period if period > 0 else rate
    if fill_rate <= 0:
        return False, 1
    wait = max(0.0, (1.0 - tokens) / fill_rate)
    retry_after = int(wait) if wait > 0 else 1
    return False, retry_after

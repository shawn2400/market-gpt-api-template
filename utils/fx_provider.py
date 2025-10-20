# utils/fx_provider.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os, time, json, asyncio
from typing import Dict, Optional, Tuple
import httpx

# Optional Redis (redis>=4, supports asyncio)
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

"""
🔹 ייעוד: שערי מט"ח (לא למסחר/טריגרים!) לדוחות/PNL/דשבורד.
- Providers: frankfurter | exchangerate_host | fixer
- Cache: Redis אם קיים, אחרת in-memory TTL
- Fail-open: אם הספק נופל → נשארים עם cache או {} בלי להפיל את המערכת
ENV:
  FX_ENABLE=1
  FX_PROVIDER=frankfurter|exchangerate_host|fixer
  FX_BASE=USD
  FX_CACHE_TTL_SEC=900
  FIXER_API_KEY=...
"""

DEFAULT_PROVIDER = os.getenv("FX_PROVIDER", "frankfurter").strip().lower() or "frankfurter"
DEFAULT_BASE = os.getenv("FX_BASE", "USD").strip().upper() or "USD"
CACHE_TTL = int(os.getenv("FX_CACHE_TTL_SEC", "900") or "900")
FX_ENABLE = (os.getenv("FX_ENABLE", "1").lower() in ("1", "true", "yes", "on"))

# Endpoints
FX_URLS = {
    "frankfurter": "https://api.frankfurter.app/latest?from={base}",
    "exchangerate_host": "https://api.exchangerate.host/latest?base={base}",
    "fixer": "https://data.fixer.io/api/latest?access_key={key}&base={base}",
}

# Shared HTTP client
_http_client: Optional[httpx.AsyncClient] = None
_http_lock = asyncio.Lock()

async def get_http_client() -> httpx.AsyncClient:
    global _http_client
    async with _http_lock:
        if _http_client is None or _http_client.is_closed:
            _http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(3.0, connect=1.0),
                headers={"User-Agent": "AlgoGPT-FX/1.0"}
            )
    return _http_client

# Redis (optional)
_redis: Optional[aioredis.Redis] = None
_redis_lock = asyncio.Lock()

async def get_redis() -> Optional["aioredis.Redis"]:
    global _redis
    if aioredis is None:
        return None
    if _redis is not None:
        return _redis
    url = os.getenv("REDIS_URL") or ""
    if not url:
        return None
    async with _redis_lock:
        if _redis is None:
            _redis = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
    return _redis

# In-memory TTL cache
_mem_cache: Dict[str, Tuple[float, Dict[str, float]]] = {}
def _mem_get(key: str) -> Optional[Dict[str, float]]:
    item = _mem_cache.get(key)
    if not item:
        return None
    ts, data = item
    if (time.time() - ts) > CACHE_TTL:
        _mem_cache.pop(key, None)
        return None
    return data

def _mem_set(key: str, value: Dict[str, float]) -> None:
    _mem_cache[key] = (time.time(), value)

async def _redis_get_json(key: str) -> Optional[Dict[str, float]]:
    r = await get_redis()
    if not r:
        return None
    raw = await r.get(key)
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return {k: float(v) for k, v in obj.items()}
    except Exception:
        return None
    return None

async def _redis_set_json(key: str, value: Dict[str, float], ttl: int) -> None:
    r = await get_redis()
    if not r:
        return
    try:
        await r.set(key, json.dumps(value), ex=ttl)
    except Exception:
        pass

def _build_url(provider: str, base: str) -> str:
    base = base.upper()
    if provider == "fixer":
        key = os.getenv("FIXER_API_KEY", "")
        return FX_URLS["fixer"].format(key=key, base=base)
    if provider == "exchangerate_host":
        return FX_URLS["exchangerate_host"].format(base=base)
    return FX_URLS["frankfurter"].format(base=base)

def _normalize(provider: str, payload: dict) -> Dict[str, float]:
    # Normalize response payload → {"EUR": 0.92, "ILS": 3.7, ...}
    if not payload:
        return {}
    if provider in ("frankfurter", "exchangerate_host"):
        return {k: float(v) for k, v in (payload.get("rates") or {}).items()}
    if provider == "fixer":
        return {k: float(v) for k, v in (payload.get("rates") or {}).items()}
    return {}

async def get_rates(base: Optional[str] = None, provider: Optional[str] = None) -> Dict[str, float]:
    """
    שליפת שערים עם Cache (Redis→Memory) ו-fail-open.
    """
    if not FX_ENABLE:
        return {}
    base = (base or DEFAULT_BASE).upper()
    provider = (provider or DEFAULT_PROVIDER).lower()
    cache_key = f"fx:{provider}:{base}"

    # 1) Redis
    try:
        data = await _redis_get_json(cache_key)
        if isinstance(data, dict) and data:
            return data
    except Exception:
        pass

    # 2) Memory
    data = _mem_get(cache_key)
    if data:
        return data

    # 3) Fetch
    url = _build_url(provider, base)
    try:
        cli = await get_http_client()
        r = await cli.get(url)
        r.raise_for_status()
        payload = r.json()
        rates = _normalize(provider, payload)
        if rates:
            await _redis_set_json(cache_key, rates, CACHE_TTL)
            _mem_set(cache_key, rates)
            return rates
    except Exception:
        # Fail-open: חזרה ל-cache אם קיים
        data = _mem_get(cache_key)
        if data:
            return data

    return {}

async def convert(amount: float, from_ccy: str, to_ccy: str, provider: Optional[str] = None) -> Optional[float]:
    """המרת מטבע (לתצוגה/דוחות בלבד)."""
    from_ccy = from_ccy.upper()
    to_ccy = to_ccy.upper()
    if from_ccy == to_ccy:
        return float(amount)

    # ממירים דרך base (ברירת מחדל: USD)
    base = DEFAULT_BASE
    rates = await get_rates(base=base, provider=provider)
    if not rates:
        return None

    def to_base(value: float, ccy: str) -> Optional[float]:
        if ccy == base:
            return value
        r = rates.get(ccy)
        if not r:
            return None
        # value [ccy] → base = value / rate_ccy
        return value / r

    amt_in_base = to_base(amount, from_ccy)
    if amt_in_base is None:
        return None

    if to_ccy == base:
        return amt_in_base

    r_to = rates.get(to_ccy)
    if not r_to:
        return None
    # base → to_ccy = amt_in_base * rate_to
    return amt_in_base * r_to

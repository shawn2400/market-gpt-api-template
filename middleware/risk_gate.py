# middleware/risk_gate.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os, time, ipaddress, asyncio
from typing import Optional, Tuple, Dict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import httpx

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

"""
🔹 ייעוד: שכבת סיכון קלה לנתיבי /ops/* ו-/telegram/* (proxy/TOR/ASN).
- Provider: IPstack (security=1)
- Cache: Redis או in-memory TTL
- Fail-open: כשאין ספק/כשל → ציון 0 (לא חוסם)
ENV:
  IPSTACK_ENABLE=1
  IPSTACK_KEY=...
  IPSTACK_TIMEOUT_MS=1200
  SECURITY_IP_SCORE_MIN=30
  RISK_PATH_PREFIXES=/ops/,/telegram/
  RISK_ALLOW_CIDRS=127.0.0.1/32,10.0.0.0/8
  RISK_DENY_CIDRS=
  RISK_BYPASS_TOKEN=...   # Header: X-Risk-Bypass: <token>
"""

IPSTACK_ENABLE = (os.getenv("IPSTACK_ENABLE", "0").lower() in ("1", "true", "yes", "on"))
IPSTACK_KEY = os.getenv("IPSTACK_KEY", "")
IPSTACK_TIMEOUT = float(int(os.getenv("IPSTACK_TIMEOUT_MS", "1200")) / 1000.0)
SEC_MIN = int(os.getenv("SECURITY_IP_SCORE_MIN", "30") or "30")

PREFIXES = [p.strip() for p in (os.getenv("RISK_PATH_PREFIXES", "/ops/,/telegram/") or "").split(",") if p.strip()]
ALLOW_CIDRS = [c.strip() for c in (os.getenv("RISK_ALLOW_CIDRS", "127.0.0.1/32") or "").split(",") if c.strip()]
DENY_CIDRS  = [c.strip() for c in (os.getenv("RISK_DENY_CIDRS", "") or "").split(",") if c.strip()]
BYPASS_TOKEN = (os.getenv("RISK_BYPASS_TOKEN") or "").strip()

_cache: Dict[str, Tuple[float, int]] = {}
CACHE_TTL = 6 * 3600  # 6h

_redis = None
_redis_lock = asyncio.Lock()

async def get_redis():
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

def _cidr_contains(cidr: str, ip: str) -> bool:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        return ipaddress.ip_address(ip) in net
    except Exception:
        return False

def _is_allowed_ip(ip: str) -> bool:
    return any(_cidr_contains(c, ip) for c in ALLOW_CIDRS)

def _is_denied_ip(ip: str) -> bool:
    return any(_cidr_contains(c, ip) for c in DENY_CIDRS)

async def _cache_get(ip: str) -> Optional[int]:
    # Redis
    try:
        r = await get_redis()
        if r:
            val = await r.get(f"risk:ip:{ip}")
            if val is not None:
                return int(val)
    except Exception:
        pass
    # memory
    item = _cache.get(ip)
    if item:
        ts, score = item
        if (time.time() - ts) < CACHE_TTL:
            return score
        _cache.pop(ip, None)
    return None

async def _cache_set(ip: str, score: int) -> None:
    # memory
    _cache[ip] = (time.time(), score)
    # Redis
    try:
        r = await get_redis()
        if r:
            await r.set(f"risk:ip:{ip}", str(score), ex=CACHE_TTL)
    except Exception:
        pass

async def ip_risk_score(ip: str) -> int:
    if not IPSTACK_ENABLE or not IPSTACK_KEY:
        return 0  # fail-open (לא חוסם)
    try:
        cached = await _cache_get(ip)
        if cached is not None:
            return cached

        url = f"http://api.ipstack.com/{ip}?access_key={IPSTACK_KEY}&security=1"
        async with httpx.AsyncClient(timeout=IPSTACK_TIMEOUT, headers={"User-Agent": "AlgoGPT-RiskGate/1.0"}) as cli:
            r = await cli.get(url)
            r.raise_for_status()
            d = r.json()

        sec = d.get("security", {}) if isinstance(d, dict) else {}
        score = 0
        # ניקוד שמרני: לא לסגור לגיטימי à priori
        score += 25 if sec.get("is_proxy") else 0
        score += 25 if sec.get("is_tor") else 0
        score += 10 if sec.get("is_crawler") else 0
        score += 10 if sec.get("is_anonymous") else 0
        # אפשר להחמיר לפי מדינה/ASN אם תרצה בעתיד

        await _cache_set(ip, score)
        return score
    except Exception:
        return 0  # fail-open

class RiskGate(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # לא כל נתיב – רק prefixes
        if not any(path.startswith(p) for p in PREFIXES):
            return await call_next(request)

        # Bypass (לבדיקות/הרשאות גבוהות)
        if BYPASS_TOKEN and request.headers.get("X-Risk-Bypass", "") == BYPASS_TOKEN:
            return await call_next(request)

        # הפקת IP (מאחורי פרוקסי)
        ip = (request.headers.get("x-forwarded-for") or request.client.host or "").split(",")[0].strip()

        if not ip:
            return await call_next(request)

        if _is_allowed_ip(ip):
            return await call_next(request)
        if _is_denied_ip(ip):
            return Response("forbidden", status_code=403)

        score = await ip_risk_score(ip)
        if score >= SEC_MIN:
            return Response("forbidden", status_code=403)

        return await call_next(request)

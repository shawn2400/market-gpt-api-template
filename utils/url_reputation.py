# utils/url_reputation.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os, re, time, json, asyncio, urllib.parse
from typing import Optional, Dict, Tuple, Literal
import httpx

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

"""
🔹 ייעוד: דירוג URL (safe/suspicious/malicious/unknown) לצורכי UI/טלגרם – לא למסחר.
Providers (אפשר לבחור יותר מאחד, יעצר על הראשון שמחזיר החלטה):
  - safebrowsing (Google) – דורש API key
  - urlscan (urlscan.io) – חינמי יחסי, rate-limit עדין
  - abuseipdb (ל-IP reputation אם ה-URL הוא IP)
Cache: Redis או in-memory TTL (ברירת מחדל 48 שעות)
ENV:
  URLREP_ENABLE=1
  URLREP_CACHE_TTL_SEC=172800
  URLREP_PROVIDERS=safebrowsing,urlscan,abuseipdb
  SAFEBROWSING_API_KEY=...
  URLSCAN_API_KEY=...
  ABUSEIPDB_API_KEY=...
"""

URLREP_ENABLE = (os.getenv("URLREP_ENABLE", "1").lower() in ("1", "true", "yes", "on"))
TTL = int(os.getenv("URLREP_CACHE_TTL_SEC", "172800") or "172800")
PROVIDERS = [p.strip() for p in (os.getenv("URLREP_PROVIDERS", "safebrowsing,urlscan,abuseipdb") or "").split(",") if p.strip()]

Verdict = Literal["safe", "suspicious", "malicious", "unknown"]

_mem: Dict[str, Tuple[float, Dict[str, str]]] = {}
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

def _norm_url(u: str) -> str:
    u = u.strip()
    if not re.match(r"^https?://", u, re.I):
        u = "http://" + u
    return u

def _cache_get(u: str) -> Optional[Dict[str, str]]:
    item = _mem.get(u)
    if item:
        ts, data = item
        if (time.time() - ts) < TTL:
            return data
        _mem.pop(u, None)
    return None

def _cache_set(u: str, obj: Dict[str, str]) -> None:
    _mem[u] = (time.time(), obj)

async def _redis_get(u: str) -> Optional[Dict[str, str]]:
    r = await get_redis()
    if not r:
        return None
    raw = await r.get(f"urlrep:{u}")
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None

async def _redis_set(u: str, obj: Dict[str, str]) -> None:
    r = await get_redis()
    if not r:
        return
    try:
        await r.set(f"urlrep:{u}", json.dumps(obj), ex=TTL)
    except Exception:
        pass

async def _provider_safebrowsing(url: str) -> Optional[Tuple[Verdict, str]]:
    key = os.getenv("SAFEBROWSING_API_KEY", "")
    if not key:
        return None
    # Google Web Risk v1 (דומה): POST threats: computeUris
    endpoint = f"https://webrisk.googleapis.com/v1/uris:search?key={key}"
    payload = {"uri": url, "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE"]}
    try:
        async with httpx.AsyncClient(timeout=2.5) as cli:
            r = await cli.get(endpoint + "&" + urllib.parse.urlencode({"uri": url, "threatTypes": "MALWARE,SOCIAL_ENGINEERING,UNWANTED_SOFTWARE"}))
            r.raise_for_status()
            data = r.json() or {}
        if data.get("threat") or data.get("threatTypes") or data.get("threatType"):
            return ("malicious", "safebrowsing:threat")
        return ("safe", "safebrowsing:clean")
    except Exception:
        return None

async def _provider_urlscan(url: str) -> Optional[Tuple[Verdict, str]]:
    key = os.getenv("URLSCAN_API_KEY", "")
    headers = {"User-Agent": "AlgoGPT-URLRep/1.0"}
    if key:
        headers["API-Key"] = key
    try:
        # חיפוש אינדקס קיים (לא לבצע סריקה אקטיבית כדי לא ליצור עומס)
        q = urllib.parse.urlencode({"q": url})
        async with httpx.AsyncClient(timeout=2.5, headers=headers) as cli:
            r = await cli.get(f"https://urlscan.io/api/v1/search/?{q}")
            if r.status_code == 429:
                return None
            r.raise_for_status()
            data = r.json() or {}
        # היוריסטיקה רכה: אם נמצאו תוצאות עם tags/verdicts שליליים
        total = int(data.get("total", 0))
        if total == 0:
            return ("unknown", "urlscan:none")
        # אם יש “malicious verdict” בשדות הידועים – נסמן suspicious
        if "results" in data:
            for item in data["results"][:5]:
                vt = (item.get("verdicts") or {}).get("overall") or {}
                if vt.get("malicious") or vt.get("score", 0) >= 6:
                    return ("suspicious", "urlscan:malicious_hint")
        return ("safe", "urlscan:seen")
    except Exception:
        return None

async def _provider_abuseipdb(url: str) -> Optional[Tuple[Verdict, str]]:
    key = os.getenv("ABUSEIPDB_API_KEY", "")
    if not key:
        return None
    try:
        host = urllib.parse.urlparse(url).hostname or ""
        # אם זה IP גולמי – נבדוק reputation
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
            async with httpx.AsyncClient(timeout=2.5) as cli:
                r = await cli.get("https://api.abuseipdb.com/api/v2/check", params={"ipAddress": host, "maxAgeInDays": 90},
                                  headers={"Key": key, "Accept": "application/json"})
                r.raise_for_status()
                d = r.json() or {}
            score = (((d.get("data") or {}).get("abuseConfidenceScore")) or 0)
            if score >= 50:
                return ("suspicious", f"abuseipdb:{score}")
            return ("safe", f"abuseipdb:{score}")
        return None
    except Exception:
        return None

async def check_url(url: str) -> Dict[str, str]:
    """
    מחזיר אובייקט:
    {
      "url": <norm>,
      "verdict": "safe|suspicious|malicious|unknown",
      "provider": "safebrowsing|urlscan|abuseipdb|none",
      "reason": "..."
    }
    """
    result = {"url": _norm_url(url), "verdict": "unknown", "provider": "none", "reason": ""}
    if not URLREP_ENABLE:
        return result

    cached = await _redis_get(result["url"])
    if not cached:
        cached = _cache_get(result["url"])
    if cached:
        return cached

    prov_funcs = {
        "safebrowsing": _provider_safebrowsing,
        "urlscan": _provider_urlscan,
        "abuseipdb": _provider_abuseipdb,
    }

    for prov in PROVIDERS:
        fn = prov_funcs.get(prov)
        if not fn:
            continue
        out = await fn(result["url"])
        if out is None:
            continue
        verdict, reason = out
        result.update({"verdict": verdict, "provider": prov, "reason": reason})
        break

    _cache_set(result["url"], result)
    await _redis_set(result["url"], result)
    return result

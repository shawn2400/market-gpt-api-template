# routes/public.py
from __future__ import annotations
import os, json, time, logging, asyncio
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("algogpt.public")
router = APIRouter(tags=["Public Feed"])

NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL = (os.getenv("REDIS_URL") or "").strip()
PUBLIC_CACHE_MAX_AGE = int(os.getenv("PUBLIC_CACHE_MAX_AGE", "20") or "20")
PUBLIC_DEMO = os.getenv("PUBLIC_DEMO", "0").lower() in ("1","true","yes","on")

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
            _redis_client = _aioredis.from_url(REDIS_URL, decode_responses=True)
        except Exception as e:
            logger.warning("public: redis connect failed: %s", e)
            _redis_client = None
    return _redis_client

async def _read_json(key: str) -> Optional[Any]:
    r = await _get_redis()
    if not r:
        return None
    try:
        raw = await r.get(key)
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.debug("public: read_json fail: %s", e)
        return None

def _demo_now() -> Dict[str, Any]:
    # חיתוך דמו שמחקה מבנה "חי": זוגות עם מחירים/שינוי
    return {
        "ts": int(time.time()),
        "items": [
            {"symbol": "BTCUSDT", "price": 64250.1, "chg_5m_pct": 0.12, "vol_5m_usd": 15_000_000},
            {"symbol": "ETHUSDT", "price": 2540.3, "chg_5m_pct": -0.08, "vol_5m_usd": 8_100_000},
        ],
    }

def _demo_topk() -> Dict[str, Any]:
    return {
        "ts": int(time.time()),
        "k": 5,
        "items": [
            {"symbol": "SOLUSDT", "score": 8.4, "side": "BUY"},
            {"symbol": "BNBUSDT", "score": 7.9, "side": "SELL"},
            {"symbol": "NEARUSDT", "score": 7.5, "side": "BUY"},
        ],
    }

@router.get("/scan/public-now")
async def public_now():
    payload = await _read_json(f"{NS}:public:now")
    if not payload:
        payload = _demo_now() if PUBLIC_DEMO else {"ts": int(time.time()), "items": []}
    resp = JSONResponse({"ok": True, **payload})
    resp.headers.setdefault("Cache-Control", f"public, max-age={PUBLIC_CACHE_MAX_AGE}")
    return resp

@router.get("/scan/public-topk")
async def public_topk(k: int = Query(5, ge=1, le=50)):
    payload = await _read_json(f"{NS}:public:topk")
    if not payload:
        base = _demo_topk() if PUBLIC_DEMO else {"ts": int(time.time()), "k": k, "items": []}
        # אם דמו מוגדר, נתחשב בפרמטר k
        if PUBLIC_DEMO and isinstance(base.get("items"), list):
            base["items"] = base["items"][:k]
        payload = base
    # ודא התאמה ל-k המבוקש
    if isinstance(payload, dict) and "items" in payload and isinstance(payload["items"], list):
        payload = {**payload, "k": min(k, len(payload["items"]))}
        payload["items"] = payload["items"][:payload["k"]]
    resp = JSONResponse({"ok": True, **payload})
    resp.headers.setdefault("Cache-Control", f"public, max-age={PUBLIC_CACHE_MAX_AGE}")
    return resp


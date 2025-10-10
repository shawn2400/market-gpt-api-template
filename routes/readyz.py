# routes/readyz.py
from __future__ import annotations
import os, time, logging
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

LOG = logging.getLogger("algogpt.readyz")
router = APIRouter()

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

REDIS_URL = os.getenv("REDIS_URL", "").strip()
REQUIRE_REDIS = (os.getenv("REQUIRE_REDIS", "1").lower() in ("1","true","yes","on"))
PING_TIMEOUT_SEC = float(os.getenv("REDIS_SOCKET_TIMEOUT", "5.0") or 5.0)

async def _ping_redis() -> bool:
    if not REQUIRE_REDIS:
        return True
    if not (aioredis and REDIS_URL):
        return False
    try:
        r = aioredis.from_url(REDIS_URL, decode_responses=True, socket_timeout=PING_TIMEOUT_SEC)
        pong = await r.ping()
        return bool(pong)
    except Exception as e:
        LOG.warning({"event": "readyz.redis_ping_failed", "error": str(e)})
        return False

def _hdrs(ok: bool) -> dict:
    return {
        "Cache-Control": "no-store",
        "X-Ready": "1" if ok else "0",
        "Last-Modified": time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime()),
    }

@router.api_route("/readyz", methods=["GET","HEAD"], summary="Readiness probe (GET/HEAD)")
async def readyz(request: Request):
    ok = await _ping_redis()
    status = 200 if ok else 503
    body = None if request.method == "HEAD" else {"ok": ok, "requires_redis": REQUIRE_REDIS}
    return JSONResponse(status_code=status, content=body, headers=_hdrs(ok))

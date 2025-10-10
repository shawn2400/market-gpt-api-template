# routes/readyz.py
from __future__ import annotations

import os
import time
import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

LOG = logging.getLogger("algogpt.readyz")
router = APIRouter()

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

REDIS_URL = os.getenv("REDIS_URL", "").strip()
REQUIRE_REDIS = os.getenv("REQUIRE_REDIS", "1").lower() in ("1", "true", "yes", "on")
PING_TIMEOUT_SEC = float(os.getenv("REDIS_SOCKET_TIMEOUT", "5.0") or 5.0)


async def _ping_redis() -> bool:
    """
    מחזיר True אם הכול כשיר. אם רדיס לא נדרש – תמיד True.
    אם נדרש ואין קונפיג/מודול – False. אם כשל בפינג – False.
    דואג לסגור את הלקוח לאחר שימוש.
    """
    if not REQUIRE_REDIS:
        return True
    if not (aioredis and REDIS_URL):
        return False

    r = None
    try:
        r = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_timeout=PING_TIMEOUT_SEC,
        )
        pong = await r.ping()
        return bool(pong)
    except Exception as e:
        LOG.warning({"event": "readyz.redis_ping_failed", "error": str(e)})
        return False
    finally:
        if r is not None:
            try:
                await r.close()
            except Exception:
                pass
            try:
                await r.connection_pool.disconnect()
            except Exception:
                pass


def _hdrs(ok: bool) -> dict:
    return {
        "Cache-Control": "no-store",
        "X-Ready": "1" if ok else "0",
        "Last-Modified": time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime()),
    }


@router.api_route("/readyz", methods=["GET", "HEAD"], summary="Readiness probe (GET/HEAD)")
async def readyz(request: Request):
    ok = await _ping_redis()
    status = 200 if ok else 503

    # ב-HEAD לא מחזירים גוף
    if request.method == "HEAD":
        return Response(status_code=status, headers=_hdrs(ok))

    return JSONResponse(status_code=status, content={"ok": ok, "requires_redis": REQUIRE_REDIS}, headers=_hdrs(ok))


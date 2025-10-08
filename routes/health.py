# routes/health.py
from __future__ import annotations

import os
import logging
from contextlib import suppress

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["Health"])
log = logging.getLogger("algogpt.health")

# ai_healthcheck אופציונלי: לא מפיל ראוט אם חסר
_ai_check = None
with suppress(Exception):
    from utils.ai_client import ai_healthcheck as _ai_check  # type: ignore


@router.get("", summary="Health Root")
async def root():
    # קליל ומהיר–לא נוגע בבורסה/רשת חיצונית
    return {"ok": True, "service": "AlgoGPT"}


@router.get("/live", summary="Liveness Probe")
async def live():
    return {"ok": True, "live": True}


@router.get("/strategy-version", summary="Get Strategy Version")
async def strategy_version():
    return {
        "ok": True,
        "ALGOGPT_VERSION": os.getenv("ALGOGPT_VERSION", "unknown"),
        "STRATEGY_VERSION": os.getenv("STRATEGY_VERSION", "unknown"),
        "GIT_COMMIT": os.getenv("GIT_COMMIT", ""),
    }


@router.get("/ai", summary="AI Health")
async def ai():
    if _ai_check is None:
        # לא מפילים את ה-health אם המודול לא קיים
        return {"ok": True, "ai": "skipped"}
    try:
        return await _ai_check()  # צריך להחזיר {"ok": ...}
    except Exception as e:  # noqa: BLE001
        log.warning("ai_healthcheck_failed: %s", e)
        # עדיין 200 — שלא יפיל health של הסרוויס
        return {"ok": False, "error": "ai_healthcheck_failed", "detail": str(e)}














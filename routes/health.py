# routes/health.py
from __future__ import annotations

import os
import time
import logging
from contextlib import suppress
from typing import Optional, Dict, Any

from fastapi import APIRouter, Response, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter(prefix="/health", tags=["Health"])
log = logging.getLogger("algogpt.health")

# ai_healthcheck אופציונלי: לא מפיל ראוט אם חסר
_ai_check = None
with suppress(Exception):
    from utils.ai_client import ai_healthcheck as _ai_check  # type: ignore

# TP1 health (אופציונלי)
_health_tp1_loaded = False
with suppress(Exception):
    from utils.health_tp1 import health_check_tp1_tags, quick_check_tp1  # type: ignore
    _health_tp1_loaded = True

WATCHLIST = [s.strip().upper() for s in (os.getenv("WATCHLIST", "") or "").split(",") if s.strip()] \
            or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "NEARUSDT"]
TP1_TAGS = [t.strip() for t in (os.getenv("TP1_TAGS", "TP1,tp1,tp_1,TAKE_PROFIT_1")).split(",") if t.strip()]


def _base_headers() -> Dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Last-Modified": time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime()),
    }


@router.get("", summary="Health Root")
async def root():
    """
    קליל ומהיר – לא נוגע בבורסה/רשת חיצונית.
    """
    return {"ok": True, "service": "AlgoGPT"}


@router.head("", include_in_schema=False)
async def root_head():
    """
    פרוב לייב/ניטור שעושים HEAD /health.
    """
    return Response(status_code=200, headers=_base_headers())


@router.api_route("/live", methods=["GET", "HEAD"], summary="Liveness Probe")
async def live(request: Request):
    if request.method == "HEAD":
        return Response(status_code=200, headers=_base_headers())
    return JSONResponse({"ok": True, "live": True}, headers=_base_headers())


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
    """
    בודק בריאות AI אם קיים מודול utils.ai_client.ai_healthcheck.
    לא מפיל את ה-health גם אם יש כשל – תמיד מחזיר 200.
    """
    if _ai_check is None:
        # לא מפילים את ה-health אם המודול לא קיים
        return {"ok": True, "ai": "skipped"}
    try:
        result = await _ai_check()  # צריך להחזיר {"ok": ...}
        return result
    except Exception as e:  # noqa: BLE001
        log.warning("ai_healthcheck_failed: %s", e)
        # עדיין 200 — שלא יפיל health של הסרוויס
        return {"ok": False, "error": "ai_healthcheck_failed", "detail": str(e)}


@router.api_route("/tp1", methods=["GET", "HEAD"], summary="TP1 heartbeat / tags check")
async def health_tp1_now(request: Request, symbols: Optional[str] = None):
    """
    בדיקת TP1 אופציונלית (אם קיים המודול). HEAD תמיד 200 ללא גוף.
    """
    if request.method == "HEAD":
        return Response(status_code=200, headers=_base_headers())

    if not _health_tp1_loaded:
        # נשמור את ההתנהגות המקורית (501) כדי שיהיה ברור שהפיצ'ר לא בנוי
        raise HTTPException(status_code=501, detail="health_tp1 module not loaded")

    sym_list = [s.strip().upper() for s in (symbols.split(",") if symbols else WATCHLIST) if s.strip()]
    if not sym_list:
        raise HTTPException(status_code=400, detail="no symbols")
    res = await quick_check_tp1(sym_list, tp1_tags=(TP1_TAGS or None), notify_telegram=True)
    return JSONResponse({"ok": True, "result": res}, headers=_base_headers())









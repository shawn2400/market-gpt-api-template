# routes/health.py
from __future__ import annotations
import os, time, logging
from contextlib import suppress
from typing import Optional, Dict, Any
from fastapi import APIRouter, Response, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter(prefix="/health", tags=["Health"])
log = logging.getLogger("algogpt.health")

_ai_check = None
with suppress(Exception):
    from utils.ai_client import ai_healthcheck as _ai_check  # type: ignore

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
    return {"ok": True, "service": "AlgoGPT"}

@router.head("", include_in_schema=False)
async def root_head():
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
    if _ai_check is None:
        return {"ok": True, "ai": "skipped"}
    try:
        result = await _ai_check()  # {"ok": ...}
        return result
    except Exception as e:
        log.warning("ai_healthcheck_failed: %s", e)
        return {"ok": False, "error": "ai_healthcheck_failed", "detail": str(e)}

@router.api_route("/tp1", methods=["GET", "HEAD"], summary="TP1 heartbeat / tags check")
async def health_tp1_now(request: Request, symbols: Optional[str] = None):
    if request.method == "HEAD":
        return Response(status_code=200, headers=_base_headers())

    if not _health_tp1_loaded:
        raise HTTPException(status_code=501, detail="health_tp1 module not loaded")

    sym_list = [s.strip().upper() for s in (symbols.split(",") if symbols else WATCHLIST) if s.strip()]
    if not sym_list:
        raise HTTPException(status_code=400, detail="no symbols")

    try:
        if 'health_check_tp1_tags' in globals():
            res = health_check_tp1_tags(sym_list, TP1_TAGS)  # type: ignore
        else:
            res = quick_check_tp1(sym_list)  # type: ignore
        return JSONResponse({"ok": True, "symbols": sym_list, "result": res}, headers=_base_headers())
    except Exception as e:
        log.warning("health_tp1 failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, headers=_base_headers(), status_code=200)









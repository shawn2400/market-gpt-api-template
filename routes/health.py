# routes/health.py
from __future__ import annotations
import os, time, logging, sqlite3
from contextlib import suppress
from typing import Optional, Dict, Tuple
from fastapi import APIRouter, Response, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

log = logging.getLogger("algogpt.health")

# ---------------------------
# Routers: /health/*  +  /readyz/* (root, ללא prefix)
# ---------------------------
router = APIRouter(prefix="/health", tags=["Health"])
probe  = APIRouter(tags=["Health"])  # שורש: /readyz/...

# --- Optional AI healthcheck (best-effort) ---
_ai_check_async = None
_ai_check_sync = None
with suppress(Exception):
    from utils.ai_client import ai_healthcheck_async as _ai_check_async  # type: ignore
with suppress(Exception):
    from utils.ai_client import ai_healthcheck as _ai_check_sync  # type: ignore

# --- Optional TP1 self-test helpers (best-effort) ---
_health_tp1_loaded = False
with suppress(Exception):
    from utils.health_tp1 import health_check_tp1_tags, quick_check_tp1  # type: ignore
    _health_tp1_loaded = True

# --- Optional metrics snapshot / prometheus text ---
_metrics_available = False
with suppress(Exception):
    from utils.metrics_tracker import get_metrics_snapshot, render_prometheus_text  # type: ignore
    _metrics_available = True

WATCHLIST = [s.strip().upper() for s in (os.getenv("WATCHLIST", "") or "").split(",") if s.strip()] \
            or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "NEARUSDT"]
TP1_TAGS = [t.strip() for t in (os.getenv("TP1_TAGS", "TP1,tp1,tp_1,TAKE_PROFIT_1")).split(",") if t.strip()]

def _base_headers() -> Dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Last-Modified": time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime()),
    }

# ------------- /health basic -------------
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
    # prefer async healthcheck if available; fallback to sync
    if _ai_check_async:
        try:
            result = await _ai_check_async()  # type: ignore
            return result
        except Exception as e:
            log.warning("ai_healthcheck_async_failed: %s", e)
            return {"ok": False, "error": "ai_healthcheck_async_failed", "detail": str(e)}
    if _ai_check_sync:
        try:
            result = _ai_check_sync()  # type: ignore
            return result
        except Exception as e:
            log.warning("ai_healthcheck_failed: %s", e)
            return {"ok": False, "error": "ai_healthcheck_failed", "detail": str(e)}
    return {"ok": True, "ai": "skipped"}

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
        # אם קיימת בדיקת תגים – העדף, אחרת quick-check
        if 'health_check_tp1_tags' in globals():
            res = health_check_tp1_tags(sym_list, TP1_TAGS)  # type: ignore
        else:
            res = quick_check_tp1(sym_list)  # type: ignore
        return JSONResponse({"ok": True, "symbols": sym_list, "result": res}, headers=_base_headers())
    except Exception as e:
        log.warning("health_tp1 failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, headers=_base_headers(), status_code=200)

# ------------- Readiness deps (with REQUIRE_REDIS) -------------

_BINANCE_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
_READINESS_BINANCE = os.getenv("READINESS_CHECK_BINANCE", "1").lower() in ("1","true","yes","on")
_READINESS_REDIS   = os.getenv("READINESS_CHECK_REDIS", "1").lower() in ("1","true","yes","on")
_READINESS_SQLITE  = os.getenv("READINESS_CHECK_SQLITE", "0").lower() in ("1","true","yes","on")
_SQLITE_PATH       = os.getenv("SQLITE_PATH", "").strip()
_REDIS_URL         = os.getenv("REDIS_URL", "").strip()
_REQUIRE_REDIS     = os.getenv("REQUIRE_REDIS", "0").lower() in ("1","true","yes","on")

async def _check_binance(timeout: float = 2.5) -> Tuple[bool, str]:
    if not _READINESS_BINANCE:
        return True, "skipped"
    try:
        import httpx
        url = f"{_BINANCE_BASE}/fapi/v1/ping"
        async with httpx.AsyncClient(timeout=timeout) as cli:
            r = await cli.get(url)
            if r.status_code < 400:
                return True, "ok"
            return False, f"http_{r.status_code}"
    except Exception as e:
        return False, f"err:{e}"

async def _check_redis(timeout: float = 1.0) -> Tuple[bool, str]:
    # אם Redis לא “נדרש” – מדלגים על הכשלה (גם אם READINESS_CHECK_REDIS=1)
    if not _REQUIRE_REDIS:
        return True, "skipped"
    if not _READINESS_REDIS or not _REDIS_URL:
        return False, "missing_url" if _REDDIS_URL else "disabled"  # type: ignore[name-defined]

    try:
        import asyncio
        import redis.asyncio as aioredis  # type: ignore
        r = aioredis.from_url(_REDIS_URL, decode_responses=True, socket_timeout=timeout)
        async def _ping():
            await r.ping()
        await asyncio.wait_for(_ping(), timeout=timeout + 0.25)
        return True, "ok"
    except Exception as e:
        return False, f"err:{e}"

def _check_sqlite() -> Tuple[bool, str]:
    if not _READINESS_SQLITE:
        return True, "skipped"
    if not _SQLITE_PATH:
        return False, "missing_path"
    try:
        conn = sqlite3.connect(_SQLITE_PATH, timeout=0.8)
        try:
            conn.execute("PRAGMA quick_check;")
        finally:
            conn.close()
        return True, "ok"
    except Exception as e:
        return False, f"err:{e}"

@router.get("/readiness", summary="Dependency readiness (Redis/Binance/DB)")
async def readiness():
    ok_bin, why_bin = await _check_binance()
    ok_rd,  why_rd  = await _check_redis()
    ok_sql, why_sql = _check_sqlite()

    overall = ok_bin and ok_rd and ok_sql
    detail = {
        "binance": {"ok": ok_bin, "detail": why_bin},
        "redis":   {"ok": ok_rd,  "detail": why_rd},
        "sqlite":  {"ok": ok_sql, "detail": why_sql, "path": _SQLITE_PATH or None},
        "require_redis": _REQUIRE_REDIS,
    }
    code = 200 if overall else 503
    return JSONResponse({"ok": overall, "deps": detail}, status_code=code, headers=_base_headers())

# ------------- /readyz (ללא prefix) עבור Render -------------

@probe.get("/readyz", include_in_schema=False)
async def readyz_light():
    # בדיקת "חיה": קלילה ומהירה
    return JSONResponse({"ok": True, "service": "AlgoGPT"}, headers=_base_headers())

@probe.get("/readyz/strict", include_in_schema=False)
async def readyz_strict():
    # שמור זהה ל-/health/readiness עבור ברירת המחדל של Render
    ok_bin, why_bin = await _check_binance()
    ok_rd,  why_rd  = await _check_redis()
    ok_sql, why_sql = _check_sqlite()

    overall = ok_bin and ok_rd and ok_sql
    detail = {
        "binance": {"ok": ok_bin, "detail": why_bin},
        "redis":   {"ok": ok_rd,  "detail": why_rd},
        "sqlite":  {"ok": ok_sql, "detail": why_sql, "path": _SQLITE_PATH or None},
        "require_redis": _REQUIRE_REDIS,
    }
    code = 200 if overall else 503
    return JSONResponse({"ok": overall, "deps": detail}, status_code=code, headers=_base_headers())

# ------------- Meta & Prometheus -------------
@router.get("/meta", summary="Service meta snapshot")
async def meta():
    if not _metrics_available:
        return {"ok": True, "metrics": "unavailable"}
    try:
        snap = get_metrics_snapshot()  # type: ignore
        return {"ok": True, "metrics": snap}
    except Exception as e:
        log.debug("meta snapshot failed: %s", e)
        return {"ok": False, "error": "meta_unavailable", "detail": str(e)}

@router.get("/metrics", summary="Prometheus metrics")
async def metrics():
    if not _metrics_available:
        return PlainTextResponse("",
                                 status_code=200,
                                 headers={"Content-Type": "text/plain; version=0.0.4"})
    try:
        text = render_prometheus_text()  # type: ignore
    except Exception as e:
        log.debug("metrics render failed: %s", e)
        text = ""
    return PlainTextResponse(text, status_code=200,
                             headers={"Content-Type": "text/plain; version=0.0.4", **_base_headers()})


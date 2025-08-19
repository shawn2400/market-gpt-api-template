# routes/health.py
from __future__ import annotations
from datetime import datetime, timezone
import os, platform
from fastapi import APIRouter

router = APIRouter(tags=["Health"])
_BOOT_TS = int(datetime.now(tz=timezone.utc).timestamp())

def _libs_meta():
    meta = {"python": platform.python_version()}
    try:
        import fastapi, starlette, uvicorn, gunicorn, httpx, requests, aiohttp
        meta.update({
            "fastapi": getattr(fastapi, "__version__", None),
            "starlette": getattr(starlette, "__version__", None),
            "uvicorn": getattr(uvicorn, "__version__", None),
            "gunicorn": getattr(gunicorn, "__version__", None),
            "httpx": getattr(httpx, "__version__", None),
            "requests": getattr(requests, "__version__", None),
            "aiohttp": getattr(aiohttp, "__version__", None),
        })
    except Exception:
        pass
    try:
        import pandas, numpy, PIL, matplotlib, openai
        meta.update({
            "pandas": getattr(pandas, "__version__", None),
            "numpy": getattr(numpy, "__version__", None),
            "Pillow": getattr(PIL, "__version__", None),
            "matplotlib": getattr(matplotlib, "__version__", None),
            "openai": getattr(openai, "__version__", None),
        })
    except Exception:
        pass
    try:
        import ta
        meta["ta"] = getattr(ta, "__version__", None)
    except Exception:
        meta["ta"] = None
    return meta

@router.get("/health", operation_id="getBasicHealth")
def health():
    return {"status": "ok", "version": os.getenv("ALGOGPT_VERSION", "unknown")}

@router.get("/health/live", operation_id="getLiveness")
def liveness():
    now = datetime.now(tz=timezone.utc).isoformat()
    return {"status": "live", "uptime_sec": int(datetime.now(tz=timezone.utc).timestamp()) - _BOOT_TS, "now_utc": now}

@router.get("/health/strategy-version", operation_id="getStrategyVersion")
def strategy_version():
    return {
        "status": "ok",
        "app_version": os.getenv("ALGOGPT_VERSION"),
        "strategy_version": os.getenv("STRATEGY_VERSION"),
        "git_commit": os.getenv("GIT_COMMIT"),
        "req_hash": os.getenv("REQ_HASH"),
        "python_version": platform.python_version(),
        "libs": _libs_meta(),
        "env_flags": {
            "execute_trades": os.getenv("EXECUTE_TRADES","false").lower() in ("1","true","yes"),
            "skip_mutations": os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS","false").lower() in ("1","true","yes"),
        },
        "boot_ts": _BOOT_TS,
        "uptime_sec": int(datetime.now(tz=timezone.utc).timestamp()) - _BOOT_TS,
        "now_utc": datetime.now(tz=timezone.utc).isoformat(),
    }


















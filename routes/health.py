# routes/health.py
from __future__ import annotations

import os
import time
import platform
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import APIRouter
from importlib import metadata as importlib_metadata

router = APIRouter(prefix="/health", tags=["Health"])

# זמן עלייה
_BOOT_TS = time.time()

def _pkg_ver(name: str) -> str | None:
    try:
        return importlib_metadata.version(name)
    except Exception:
        return None

@router.get("/live", summary="Liveness probe", operation_id="getLiveness")
async def health_live() -> Dict[str, Any]:
    return {
        "status": "live",
        "uptime_sec": int(time.time() - _BOOT_TS),
        "now_utc": datetime.now(timezone.utc).isoformat(),
    }

@router.get("/basic", summary="Basic health check", operation_id="getBasicHealth")
async def health_basic() -> Dict[str, Any]:
    return {
        "status": "ok",
        "uptime_sec": int(time.time() - _BOOT_TS),
        "now_utc": datetime.now(timezone.utc).isoformat(),
    }

@router.get("/strategy-version", summary="Strategy metadata & dependency versions", operation_id="getStrategyVersion")
async def health_strategy_version() -> Dict[str, Any]:
    app_version = os.getenv("ALGOGPT_VERSION", "unknown")
    strategy_version = os.getenv("STRATEGY_VERSION", app_version)

    libs = {
        "python": platform.python_version(),
        "fastapi": _pkg_ver("fastapi"),
        "starlette": _pkg_ver("starlette"),
        "uvicorn": _pkg_ver("uvicorn"),
        "gunicorn": _pkg_ver("gunicorn"),
        "httpx": _pkg_ver("httpx"),
        "requests": _pkg_ver("requests"),
        "aiohttp": _pkg_ver("aiohttp"),
        "pandas": _pkg_ver("pandas"),
        "numpy": _pkg_ver("numpy"),
        "ta": _pkg_ver("ta"),
        "python-binance": _pkg_ver("python-binance"),
        "openai": _pkg_ver("openai"),
        "fpdf2": _pkg_ver("fpdf2"),
        "Pillow": _pkg_ver("Pillow"),
        "matplotlib": _pkg_ver("matplotlib"),
    }

    env_flags = {
        "execute_trades": str(os.getenv("EXECUTE_TRADES", "false")).lower() in ("1", "true", "yes", "on"),
        "skip_mutations": str(os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "true")).lower() in ("1", "true", "yes", "on"),
    }

    return {
        "status": "ok",
        "app_version": app_version,
        "strategy_version": strategy_version,
        "git_commit": os.getenv("GIT_COMMIT", None),
        "req_hash": os.getenv("REQ_HASH", None),
        "python_version": libs["python"],
        "libs": libs,
        "env_flags": env_flags,
        "boot_ts": int(_BOOT_TS),
        "uptime_sec": int(time.time() - _BOOT_TS),
        "now_utc": datetime.now(timezone.utc).isoformat(),
    }

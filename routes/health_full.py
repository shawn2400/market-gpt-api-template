# routes/health_full.py
from __future__ import annotations

import os
import time
import platform
from typing import Dict, Any

from fastapi import APIRouter
from importlib.metadata import version, PackageNotFoundError

router = APIRouter(tags=["Health"])

_BOOT_TS = int(time.time())

def _safe_ver(pkg: str) -> str | None:
    try:
        return version(pkg)
    except PackageNotFoundError:
        return None
    except Exception:
        return None

def _collect_libs() -> Dict[str, str | None]:
    libs = [
        "fastapi", "starlette", "uvicorn", "gunicorn",
        "httpx", "requests", "aiohttp",
        "pydantic", "python-dotenv", "ujson", "PyYAML",
        "pandas", "numpy", "ta",
        "python-binance", "websockets",
        "openai", "fpdf2", "Pillow", "matplotlib",
    ]
    return {k: _safe_ver(k) for k in libs}

@router.get(
    "/health",
    summary="Basic health",
    operation_id="getBasicHealth",
)
async def basic_health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "version": os.getenv("ALGOGPT_VERSION", "unknown"),
    }

@router.get(
    "/health/strategy-version",
    summary="Strategy metadata & dependency versions",
    operation_id="getStrategyVersion",
)
async def strategy_version() -> Dict[str, Any]:
    app_ver = os.getenv("ALGOGPT_VERSION", "unknown")
    strat_ver = os.getenv("STRATEGY_VERSION", app_ver)
    return {
        "status": "ok",
        "app_version": app_ver,
        "strategy_version": strat_ver,
        "git_commit": os.getenv("GIT_COMMIT"),
        "req_hash": os.getenv("REQ_HASH"),
        "python_version": platform.python_version(),
        "libs": _collect_libs(),
        "env_flags": {
            "execute_trades": os.getenv("EXECUTE_TRADES", "false").lower() in ("1", "true", "yes", "on"),
            "skip_mutations": os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "true").lower() in ("1", "true", "yes", "on"),
        },
        "boot_ts": _BOOT_TS,
        "uptime_sec": int(time.time()) - _BOOT_TS,
        "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

@router.get(
    "/health/live",
    summary="Liveness probe",
    operation_id="getLiveness",
)
async def liveness() -> Dict[str, Any]:
    return {
        "status": "live",
        "uptime_sec": int(time.time()) - _BOOT_TS,
        "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }





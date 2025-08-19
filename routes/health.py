# routes/health.py
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["Health"])

BOOT_TS = int(datetime.now(tz=timezone.utc).timestamp())

class BasicStatus(BaseModel):
    status: str = Field("ok", examples=["ok"])
    version: str = Field(..., examples=["2.14.3"])

@router.get("/health", response_model=BasicStatus, operation_id="getBasicHealth")
def health() -> BasicStatus:
    return BasicStatus(status="ok", version=os.getenv("ALGOGPT_VERSION", "unknown"))

@router.get("/health/live", operation_id="getLiveness")
def liveness() -> Dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "status": "live",
        "uptime_sec": int(datetime.now(tz=timezone.utc).timestamp()) - BOOT_TS,
        "now_utc": now,
    }

@router.get("/health/strategy-version", operation_id="getStrategyVersion")
def strategy_version() -> Dict[str, Any]:
    def _ver(mod: str) -> str | None:
        try:
            m = __import__(mod)
            return getattr(m, "__version__", None) or getattr(m, "version", None)
        except Exception:
            return None

    libs = {
        "python": sys.version.split()[0],
        "fastapi": _ver("fastapi"),
        "starlette": _ver("starlette"),
        "uvicorn": _ver("uvicorn"),
        "gunicorn": _ver("gunicorn"),
        "httpx": _ver("httpx"),
        "requests": _ver("requests"),
        "aiohttp": _ver("aiohttp"),
        "pandas": _ver("pandas"),
        "numpy": _ver("numpy"),
        "ta": _ver("ta"),
        "python-binance": _ver("binance"),
        "openai": _ver("openai"),
        "fpdf2": _ver("fpdf"),
        "Pillow": _ver("PIL"),
        "matplotlib": _ver("matplotlib"),
    }

    return {
        "status": "ok",
        "app_version": os.getenv("ALGOGPT_VERSION", "unknown"),
        "strategy_version": os.getenv("STRATEGY_VERSION", os.getenv("ALGOGPT_VERSION", "unknown")),
        "git_commit": os.getenv("GIT_COMMIT"),
        "req_hash": os.getenv("REQ_HASH"),
        "python_version": libs["python"],
        "libs": libs,
        "env_flags": {
            "execute_trades": os.getenv("EXECUTE_TRADES", "false").lower() in ("1", "true", "yes"),
            "skip_mutations": os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "false").lower() in ("1", "true", "yes"),
        },
        "boot_ts": BOOT_TS,
        "uptime_sec": int(datetime.now(tz=timezone.utc).timestamp()) - BOOT_TS,
        "now_utc": datetime.now(tz=timezone.utc).isoformat(),
    }














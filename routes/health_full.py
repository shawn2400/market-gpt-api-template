# routes/health_full.py
from __future__ import annotations

import os
import time
import platform
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["Health"])

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.14.0")
STRATEGY_VERSION = os.getenv("STRATEGY_VERSION", APP_VERSION)
BOOT_TS = int(time.time())

class StrategyVersionEnvFlags(BaseModel):
    execute_trades: bool
    skip_mutations: bool

class StrategyVersionResponse(BaseModel):
    status: str = Field(example="ok")
    app_version: str = Field(example="2.14.0")
    strategy_version: str = Field(example="2.14.0")
    git_commit: Optional[str] = None
    req_hash: Optional[str] = None
    python_version: str
    libs: Dict[str, Optional[str]] = {}
    env_flags: StrategyVersionEnvFlags
    boot_ts: int
    uptime_sec: int
    now_utc: str

class BasicHealthResponse(BaseModel):
    status: str = "ok"
    version: str = APP_VERSION

class LiveResponse(BaseModel):
    status: str = "live"
    uptime_sec: int
    now_utc: str

def _get_lib_versions() -> Dict[str, Optional[str]]:
    def _v(modname: str) -> Optional[str]:
        try:
            mod = __import__(modname)
            return getattr(mod, "__version__", None)
        except Exception:
            return None

    libs = {
        "fastapi": _v("fastapi"),
        "starlette": _v("starlette"),
        "httpx": _v("httpx"),
        "pydantic": _v("pydantic"),
        "numpy": _v("numpy"),
        "pandas": _v("pandas"),
        "python_binance": _v("binance"),
        "openai": _v("openai"),
        "ta": _v("ta"),
        "fpdf2": _v("fpdf"),
        "Pillow": _v("PIL"),
        "matplotlib": _v("matplotlib"),
        "requests": _v("requests"),
        "aiohttp": _v("aiohttp"),
        "ujson": _v("ujson"),
    }
    if libs["Pillow"] is None:
        try:
            from PIL import Image
            libs["Pillow"] = getattr(Image, "__version__", None)
        except Exception:
            pass
    return libs

def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

@router.get("/health", tags=["Config"], summary="Basic health", operation_id="getBasicHealth", response_model=BasicHealthResponse)
async def basic_health():
    return BasicHealthResponse(status="ok", version=APP_VERSION)

@router.get("/health/strategy-version", summary="Strategy metadata & dependency versions", operation_id="getStrategyVersion", response_model=StrategyVersionResponse)
async def strategy_version():
    uptime = int(time.time()) - BOOT_TS
    libs = _get_lib_versions()
    pyver = platform.python_version()
    flags = StrategyVersionEnvFlags(
        execute_trades=os.getenv("EXECUTE_TRADES", "false").strip().lower() in ("1", "true", "yes", "on"),
        skip_mutations=os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "true").strip().lower() in ("1", "true", "yes", "on"),
    )
    return StrategyVersionResponse(
        status="ok",
        app_version=APP_VERSION,
        strategy_version=STRATEGY_VERSION,
        git_commit=os.getenv("GIT_COMMIT") or None,
        req_hash=os.getenv("REQ_HASH") or None,
        python_version=pyver,
        libs=libs,
        env_flags=flags,
        boot_ts=BOOT_TS,
        uptime_sec=uptime,
        now_utc=_now_iso_utc(),
    )

@router.get("/health/live", summary="Liveness probe", operation_id="getLiveness", response_model=LiveResponse)
async def liveness():
    uptime = int(time.time()) - BOOT_TS
    return LiveResponse(status="live", uptime_sec=uptime, now_utc=_now_iso_utc())










# routes/health.py
from __future__ import annotations
from datetime import datetime, timezone
import os, platform
from importlib.metadata import version as _pkg_version, PackageNotFoundError
from fastapi import APIRouter

router = APIRouter(tags=["Health"])
_BOOT_TS = int(datetime.now(tz=timezone.utc).timestamp())

def _get_pkg_ver(name: str):
    try:
        return _pkg_version(name)
    except PackageNotFoundError:
        return None

def _libs_meta():
    meta = {"python": platform.python_version()}
    try:
        import fastapi, starlette, uvicorn, gunicorn, httpx, requests, aiohttp  # noqa: F401
        meta.update({
            "fastapi": _get_pkg_ver("fastapi"),
            "starlette": _get_pkg_ver("starlette"),
            "uvicorn": _get_pkg_ver("uvicorn"),
            "gunicorn": _get_pkg_ver("gunicorn"),
            "httpx": _get_pkg_ver("httpx"),
            "requests": _get_pkg_ver("requests"),
            "aiohttp": _get_pkg_ver("aiohttp"),
        })
    except Exception:
        pass
    meta.update({
        "pandas": _get_pkg_ver("pandas"),
        "numpy": _get_pkg_ver("numpy"),
        "Pillow": _get_pkg_ver("Pillow"),
        "matplotlib": _get_pkg_ver("matplotlib"),
        "openai": _get_pkg_ver("openai"),
        "ta": _get_pkg_ver("ta"),
        "pandas_ta": _get_pkg_ver("pandas-ta"),
    })
    return meta

@router.get("/health", operation_id="getBasicHealth")
def health():
    return {"status": "ok", "version": os.getenv("ALGOGPT_VERSION", "unknown")}

@router.get("/health/live", operation_id="getLiveness")
def liveness():
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "status": "live",
        "uptime_sec": int(datetime.now(tz=timezone.utc).timestamp()) - _BOOT_TS,
        "now_utc": now
    }

@router.get("/health/strategy-version", operation_id="getStrategyVersion")
def strategy_version():
    # מגבלות (רק אם נדרש לחשוף)
    limits = None
    try:
        from utils import config as cfg  # type: ignore
        if getattr(cfg, "EXPOSE_LIMITS", True):
            limits = {
                "response_max_bytes": getattr(cfg, "RESPONSE_MAX_BYTES", None),
                "scan_max_limit": getattr(cfg, "SCAN_MAX_LIMIT", None),
            }
    except Exception:
        limits = None

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
        "limits": limits,
        "boot_ts": _BOOT_TS,
        "uptime_sec": int(datetime.now(tz=timezone.utc).timestamp()) - _BOOT_TS,
        "now_utc": datetime.now(tz=timezone.utc).isoformat(),
    }





















































































































































































































































































































































































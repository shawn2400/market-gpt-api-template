# routes/health.py
from __future__ import annotations
from datetime import datetime, timezone
import os, platform
from fastapi import APIRouter

router = APIRouter(tags=["Health"])
_BOOT_TS = int(datetime.now(tz=timezone.utc).timestamp())

def _ver(name: str):
    try:
        import importlib.metadata as md
        return md.version(name)
    except Exception:
        try:
            mod = __import__(name)
            return getattr(mod, "__version__", None)
        except Exception:
            return None

def _libs_meta():
    return {
        "python": platform.python_version(),
        "fastapi": _ver("fastapi"),
        "starlette": _ver("starlette"),
        "uvicorn": _ver("uvicorn"),
        "gunicorn": _ver("gunicorn"),
        "httpx": _ver("httpx"),
        "requests": _ver("requests"),
        "aiohttp": _ver("aiohttp"),
        "pandas": _ver("pandas"),
        "numpy": _ver("numpy"),
        "ta": _ver("ta"),               # ← חשוב לראות אם ta נטען
        "openai": _ver("openai"),
        "Pillow": _ver("Pillow"),
        "matplotlib": _ver("matplotlib"),
    }

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


















# routes/health.py
from __future__ import annotations
import time
import importlib.metadata as md
from fastapi import APIRouter
from utils import config

router = APIRouter(prefix="/health", tags=["Health"])

def _v(pkg: str) -> str:
    try:
        return md.version(pkg)
    except Exception:
        return "n/a"

@router.get("/strategy-version")
async def strategy_version():
    m = config.strategy_meta_snapshot()
    return {
        "ok": True,
        "ts": int(time.time()),
        "strategy": {
            "name": m["name"],
            "version": m["version"],
            "git_commit": m["git_commit"],
            "req_hash": m["req_hash"],
        },
        "params": m["params"],
        "flags": {
            "ENABLE_AUTO_TRADING": bool(getattr(config, "ENABLE_AUTO_TRADING", False)),
            "EXECUTE_TRADES": bool(getattr(config, "EXECUTE_TRADES", False)),
            "BINANCE_SKIP_ACCOUNT_MUTATIONS": bool(getattr(config, "BINANCE_SKIP_ACCOUNT_MUTATIONS", True)),
        },
        "deps": {
            "fastapi": _v("fastapi"),
            "starlette": _v("starlette"),
            "uvicorn": _v("uvicorn"),
            "pandas": _v("pandas"),
            "numpy": _v("numpy"),
            "ta": _v("ta"),
            "python-binance": _v("python-binance"),
            "openai": _v("openai"),
        },
    }

@router.get("/live")
async def live():
    return {"ok": True}

# routes/debug.py
from __future__ import annotations
from fastapi import APIRouter, Query, Depends
from typing import Dict, Any
import os, platform, time, traceback

try:
    import psutil  # optional
except Exception:
    psutil = None  # type: ignore

from utils.auth import require_api_key, get_loaded_tokens, refresh_tokens_from_env

router = APIRouter(
    prefix="/debug",
    tags=["Debug"],
    dependencies=[Depends(require_api_key)],
)

@router.get("")
@router.get("/")
def debug_router(
    op: str = Query("ping", pattern="^(ping|health|tokens|refresh)$")
) -> Dict[str, Any]:
    """
    Debug endpoint:
      /debug?op=ping     → pong
      /debug?op=health   → CPU, memory, env
      /debug?op=tokens   → loaded tokens (masked)
      /debug?op=refresh  → reload tokens from ENV
    """
    try:
        if op == "ping":
            return {"ok": True, "event": "ping", "pong": "ok"}

        if op == "health":
            mem: Dict[str, Any]
            cpu = None
            if psutil:
                vm = psutil.virtual_memory()
                mem = {
                    "total_mb": round(vm.total / (1024 * 1024), 2),
                    "used_mb": round(vm.used / (1024 * 1024), 2),
                    "free_mb": round(vm.available / (1024 * 1024), 2),
                    "percent": vm.percent,
                }
                cpu = psutil.cpu_percent(interval=0.3)
            else:
                mem = {"note": "psutil not installed"}

            return {
                "ok": True,
                "event": "health",
                "env": os.getenv("ENV", "production"),
                "platform": platform.platform(),
                "time_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
                "cpu_percent": cpu,
                "memory": mem,
            }

        if op == "tokens":
            return {
                "ok": True,
                "event": "tokens",
                "count": len(get_loaded_tokens(mask=True)),
                "tokens_masked": get_loaded_tokens(mask=True),
            }

        if op == "refresh":
            count = refresh_tokens_from_env()
            return {
                "ok": True,
                "event": "refresh",
                "detail": "Tokens reloaded from environment.",
                "count": count,
            }

        return {"ok": False, "event": "invalid", "detail": f"Unknown op={op}"}

    except Exception as e:
        return {
            "ok": False,
            "event": "error",
            "error": str(e),
            "traceback": traceback.format_exc().splitlines()[-5:],  # רק 5 שורות אחרונות
        }
















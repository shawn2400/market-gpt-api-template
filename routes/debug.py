# routes/debug.py
from __future__ import annotations
from fastapi import APIRouter, Query, Depends
from typing import Dict, Any
import os, platform, time

try:
    import psutil  # optional
except Exception:
    psutil = None  # type: ignore

from utils.auth import require_api_key, get_loaded_tokens, refresh_tokens_from_env

router = APIRouter(prefix="/debug", tags=["Debug"], dependencies=[Depends(require_api_key)])

# תומך גם /debug וגם /debug/
@router.get("")
@router.get("/")
def debug_router(
    # FastAPI/Pydantic v2 → pattern; (אם אתה על v1, Query(..., regex=) גם יעבוד אבל pattern עדכני)
    op: str = Query("ping", pattern="^(ping|health|tokens|refresh)$")
) -> Dict[str, Any]:
    if op == "ping":
        return {"ok": True, "pong": "ok"}

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
            "env": os.getenv("ENV", "production"),
            "platform": platform.platform(),
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            "cpu_percent": cpu,
            "memory": mem,
        }

    if op == "tokens":
        return {"ok": True, "count": len(get_loaded_tokens(mask=True)), "tokens_masked": get_loaded_tokens(mask=True)}

    if op == "refresh":
        count = refresh_tokens_from_env()
        return {"ok": True, "detail": "Tokens reloaded from environment.", "count": count}

    return {"ok": False, "detail": "Unknown op"}















# routes/debug.py
from __future__ import annotations
from fastapi import APIRouter
from typing import Dict, Any
import os, platform, time, psutil

from utils.auth import get_loaded_tokens, refresh_tokens_from_env

router = APIRouter(prefix="/debug", tags=["Debug"])

@router.get("/health")
def debug_health() -> Dict[str, Any]:
    """מידע Debug בסיסי + שימוש ב־CPU וזיכרון"""
    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.5)

    return {
        "ok": True,
        "env": os.getenv("ENV", "production"),
        "platform": platform.platform(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "cpu_percent": cpu,
        "memory": {
            "total_mb": round(vm.total / (1024 * 1024), 2),
            "used_mb": round(vm.used / (1024 * 1024), 2),
            "free_mb": round(vm.available / (1024 * 1024), 2),
            "percent": vm.percent,
        },
    }

@router.get("/ping")
def debug_ping() -> Dict[str, str]:
    """בדיקת זמינות (פינג לשרת)"""
    return {"pong": "ok"}

@router.get("/tokens")
def debug_tokens() -> Dict[str, Any]:
    """מציג מידע על הטוקנים הטעונים (לא את הערכים עצמם)"""
    tokens = list(get_loaded_tokens())
    return {
        "ok": True,
        "count": len(tokens),
        "tokens": tokens,
    }

@router.post("/tokens/refresh")
def debug_tokens_refresh() -> Dict[str, Any]:
    """מאפס טעינה של טוקנים מה-ENV (ללא ריסטארט לשרת)"""
    count = refresh_tokens_from_env()
    return {"ok": True, "count": count}








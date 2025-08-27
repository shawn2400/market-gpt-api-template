# routes/debug.py
from __future__ import annotations
from fastapi import APIRouter
from typing import Dict, Any
import os, platform, time, psutil

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

        # 🔍 מידע עומסים
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







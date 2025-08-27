# routes/debug.py
from __future__ import annotations
from fastapi import APIRouter
from typing import Dict, Any
import os, platform, time, psutil

router = APIRouter(prefix="/debug", tags=["Debug"])

@router.get("/health")
def debug_health() -> Dict[str, Any]:
    """מצב מערכת (Health Debug)"""
    return {
        "ok": True,
        "env": os.getenv("ENV", "production"),
        "platform": platform.platform(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory": dict(psutil.virtual_memory()._asdict()),
    }

@router.get("/ping")
def debug_ping() -> Dict[str, str]:
    """בדיקת זמינות השרת (Ping)"""
    return {"pong": "ok"}







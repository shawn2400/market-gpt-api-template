# routes/debug.py
from __future__ import annotations
from fastapi import APIRouter
from typing import Dict
import os, platform, time

router = APIRouter(prefix="/debug", tags=["Debug"])

@router.get("/health")
def debug_health() -> Dict[str, Any]:
    """מידע Debug בסיסי"""
    return {
        "ok": True,
        "env": os.getenv("ENV", "production"),
        "platform": platform.platform(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    }

@router.get("/ping")
def debug_ping() -> Dict[str, str]:
    """בדיקת זמינות (פינג לשרת)"""
    return {"pong": "ok"}





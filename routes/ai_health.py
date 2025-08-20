# routes/ai_health.py
from __future__ import annotations
from fastapi import APIRouter
from typing import Dict, Any
import time

from utils.ai_client import ai_client, ai_healthcheck

router = APIRouter(prefix="/ai", tags=["AI"])

@router.get("/health", summary="AI Health Check")
async def ai_health() -> Dict[str, Any]:
    """
    Health check for AI (OpenAI/GPT).
    - שולח prompt קטן ("ping") ובודק תשובה.
    - מחזיר latency, reply, מצב חיבור ועוד.
    """
    t0 = time.perf_counter()
    try:
        result = await ai_healthcheck()
        latency = (time.perf_counter() - t0) * 1000.0
        return {
            "ok": result.get("ok", False),
            "reply": result.get("reply"),
            "model": result.get("model"),
            "mode": result.get("mode"),
            "base": result.get("base"),
            "latency_ms": latency,
            "error": result.get("error"),
        }
    except Exception as e:
        latency = (time.perf_counter() - t0) * 1000.0
        return {
            "ok": False,
            "error": str(e),
            "latency_ms": latency,
            "model": ai_client and getattr(ai_client, "model", None),
        }












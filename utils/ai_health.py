# routes/ai_health.py
import time
import logging
from typing import Dict, Any

from fastapi import APIRouter
from utils.ai_client import ai_healthcheck

router = APIRouter(tags=["AI"])

@router.get("/ai/health", operation_id="getAiHealth")
async def ai_health() -> Dict[str, Any]:
    """
    API Health Endpoint: מבצע פינג ל-AI ומחזיר סטטוס מלא.
    """
    t0 = time.perf_counter()
    try:
        res = await ai_healthcheck()
        dt = (time.perf_counter() - t0) * 1000.0
        return {
            "ok": bool(res.get("ok", False)),
            "model": res.get("model"),
            "latency_ms": round(dt, 2),
            "reply": res.get("reply"),
            "error": res.get("error"),
        }
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000.0
        logging.warning("[ai_health] endpoint failed after %.2f ms: %s", dt, e)
        return {"ok": False, "model": None, "latency_ms": round(dt, 2), "reply": None, "error": str(e)}







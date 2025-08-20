# routes/ai_health.py
import time
import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from utils.ai_client import ai_healthcheck

# יצירת router
router = APIRouter()

@router.get("/ai/health")
async def ai_health() -> Dict[str, Any]:
    """
    Health check ל־OpenAI/Azure.
    שולח ping → מצפה ל־pong/תשובה כלשהי.
    מחזיר מבנה JSON עם ok, reply, latency, model, ועוד מידע דיבאג.
    """
    t0 = time.time()
    try:
        result = await ai_healthcheck()
        latency_ms = round((time.time() - t0) * 1000)

        # דואגים שתמיד יוחזר latency_ms גם אם כבר קיים בפנים
        result["latency_ms"] = latency_ms

        return JSONResponse(content=result, status_code=200)
    except Exception as e:
        dt = round((time.time() - t0) * 1000)
        logging.warning(f"[ai_health] failed after {dt} ms: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"ok": False, "error": str(e), "latency_ms": dt},
        )








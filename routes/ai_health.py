# routes/ai_health.py
from __future__ import annotations
import time
import logging
from fastapi import APIRouter

from utils.ai_client import ai_healthcheck

router = APIRouter(prefix="/ai", tags=["AI"])

@router.get("/health", summary="AI health check")
async def get_ai_health():
    t0 = time.perf_counter()
    try:
        res = await ai_healthcheck()
        dt_ms = (time.perf_counter() - t0) * 1000.0
        res["latency_ms"] = dt_ms
        # ✅ החזר גם את התשובה (reply) אם קיימת
        return res
    except Exception as e:
        logging.exception("ai_health failed")
        return {"ok": False, "error": str(e), "latency_ms": None}











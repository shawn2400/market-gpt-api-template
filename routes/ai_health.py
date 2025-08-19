# routes/ai_health.py
from __future__ import annotations
import time
from typing import Dict, Any
from fastapi import APIRouter

router = APIRouter(tags=["AI"])

@router.get("/ai/health", operation_id="getAiHealth")
async def ai_health() -> Dict[str, Any]:
    try:
        t0 = time.perf_counter()
        from utils.ai_client import ai_healthcheck  # type: ignore
        res = await ai_healthcheck()
        dt = (time.perf_counter() - t0) * 1000.0
        return {"ok": bool(res.get("ok", False)), "model": res.get("model"), "latency_ms": dt, "error": res.get("error")}
    except Exception as e:
        return {"ok": False, "model": None, "latency_ms": None, "error": str(e)}











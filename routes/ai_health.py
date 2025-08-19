# routes/ai_health.py
from __future__ import annotations
from fastapi import APIRouter
from time import perf_counter

router = APIRouter(tags=["AI"])

@router.get("/ai/health", operation_id="getAiHealth")
async def ai_health():
    try:
        from utils.ai_client import ai_healthcheck  # async
        t0 = perf_counter()
        res = await ai_healthcheck()
        dt = (perf_counter() - t0) * 1000.0
        return {
            "ok": bool(res.get("ok")),
            "model": res.get("model"),
            "latency_ms": round(dt, 2),
            "mode": res.get("mode"),
            "base": res.get("base"),
            "http2": res.get("http2"),
            "error": res.get("error"),
        }
    except Exception as e:
        return {"ok": False, "model": None, "latency_ms": None, "error": str(e)}









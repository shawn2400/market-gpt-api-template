# routes/ai_health.py
from __future__ import annotations
import time
from fastapi import APIRouter

router = APIRouter(tags=["AI"])

@router.get("/ai/health", operation_id="getAiHealth")
async def get_ai_health():
    try:
        t0 = time.perf_counter()
        from utils.ai_client import ai_healthcheck  # type: ignore
        res = await ai_healthcheck()
        dt = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "ok": bool(res.get("ok")),
            "model": res.get("model"),
            "latency_ms": dt,
            "mode": res.get("mode"),
            "base": res.get("base"),
            "http2": res.get("http2"),
            "reply": res.get("reply"),
            "error": res.get("error"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}







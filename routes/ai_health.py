# routes/ai_health.py
from __future__ import annotations
import time
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Any, Dict

router = APIRouter(tags=["AI"])

class AiHealthResponse(BaseModel):
    ok: bool
    model: Optional[str] = None
    latency_ms: Optional[float] = None
    error: Optional[str] = None

@router.get("/ai/health", response_model=AiHealthResponse, operation_id="getAiHealth")
async def get_ai_health() -> AiHealthResponse:
    try:
        t0 = time.perf_counter()
        from utils.ai_client import ai_healthcheck  # type: ignore
        data: Dict[str, Any] = await ai_healthcheck()
        dt_ms = (time.perf_counter() - t0) * 1000.0
        return AiHealthResponse(
            ok=bool(data.get("ok", False)),
            model=(data.get("model") or data.get("azure_deployment")),
            latency_ms=dt_ms,
            error=data.get("error"),
        )
    except Exception as e:
        return AiHealthResponse(ok=False, model=None, latency_ms=None, error=str(e))




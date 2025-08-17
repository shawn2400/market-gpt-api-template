# routes/ai_health.py
from __future__ import annotations
import os
import time
from typing import Optional, Dict, Any
from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["AI"])

class AiHealthResponse(BaseModel):
    ok: bool = Field(True, description="Is AI service healthy")
    model: Optional[str] = Field(None, description="Model name (if known)")
    latency_ms: Optional[float] = Field(None, description="Ping latency (ms)")
    error: Optional[str] = Field(None, description="Error details if not ok")

# אם יש util פנימי – נשתמש בו, אחרת fallback
try:
    from utils.ai_health import ai_health_check as _ai_health_check  # type: ignore
except Exception:
    _ai_health_check = None  # type: ignore

@router.get("/ai/health", response_model=AiHealthResponse, operation_id="getAiHealth")
async def get_ai_health() -> AiHealthResponse:
    if _ai_health_check:
        try:
            t0 = time.perf_counter()
            res: Dict[str, Any] = await _ai_health_check()
            dt = (time.perf_counter() - t0) * 1000.0
            return AiHealthResponse(
                ok=bool(res.get("ok", True)),
                model=res.get("model"),
                latency_ms=float(res.get("latency_ms") or dt),
                error=res.get("error"),
            )
        except Exception as e:
            return AiHealthResponse(ok=False, model=None, latency_ms=None, error=str(e))

    model_hint = os.getenv("OPENAI_MODEL") or os.getenv("OPENAI_DEFAULT_MODEL") or "openai"
    has_key = bool((os.getenv("OPENAI_API_KEY") or "").strip())
    if not has_key:
        return AiHealthResponse(ok=False, model=model_hint, latency_ms=None, error="OPENAI_API_KEY missing")
    return AiHealthResponse(ok=True, model=model_hint, latency_ms=None, error=None)

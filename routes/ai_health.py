# routes/ai_health.py
from __future__ import annotations
import os
import time
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["AI"])  # פומבי (ללא Depends על אימות)

class AiHealthResponse(BaseModel):
    ok: bool = Field(..., description="True אם חיבור ה-AI זמין ועונה")
    model: Optional[str] = Field(None, description="שם המודל המדווח/מוקנפג")
    latency_ms: Optional[float] = Field(None, description="זמן תגובה מוערך במילישניות")
    error: Optional[str] = Field(None, description="טקסט שגיאה אם נכשל")

@router.get("/ai/health", response_model=AiHealthResponse, operation_id="getAiHealth")
async def get_ai_health() -> AiHealthResponse:
    """
    בדיקת חיבור ל-OpenAI/Azure OpenAI דרך שכבת ai_client.
    לא זורק 500 — תמיד מחזיר גוף תקין עם ok/error.
    """
    # מודל משוער מהסביבה במקרה שאין תשובה מהלקוח
    env_model = (os.getenv("OPENAI_MODEL") or "").strip() or None

    # ננסה להשתמש ב-utils.ai_client אם קיים
    try:
        from utils.ai_client import ai_client  # type: ignore
    except Exception as e:
        return AiHealthResponse(ok=False, model=env_model, latency_ms=None, error=f"ai_client import failed: {e}")

    t0 = time.perf_counter()
    try:
        # אם הלקוח לא מחומם, לא נכשיל — פשוט ננסה, זה גם יחמם.
        res = await ai_client.ai_healthcheck()
        dt_ms = (time.perf_counter() - t0) * 1000.0

        ok = bool(res.get("ok", False))
        model = res.get("model") or env_model
        err = None if ok else (res.get("error") or "healthcheck failed")

        return AiHealthResponse(ok=ok, model=model, latency_ms=dt_ms, error=err)
    except Exception as e:
        return AiHealthResponse(ok=False, model=env_model, latency_ms=None, error=str(e))




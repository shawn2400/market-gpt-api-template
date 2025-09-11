from __future__ import annotations

try:
    # Use the real AI router if present
    from .ai import router  # type: ignore
except Exception:
    # Safe fallback shim
    from fastapi import APIRouter, HTTPException

    router = APIRouter(tags=["ai"], prefix="/ai")

    @router.post("/analyze")
    async def analyze_fallback():
        raise HTTPException(status_code=503, detail="AI analyze module not installed")



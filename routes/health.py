# routes/health.py
from fastapi import APIRouter
from utils.ai_client import ai_healthcheck

router = APIRouter(prefix="/health", tags=["Health"])

@router.get("", summary="Health Root")
async def root():
    return {"ok": True, "service": "AlgoGPT"}

@router.get("/live", summary="Liveness Probe")
async def live():
    return {"ok": True, "live": True}

@router.get("/strategy-version", summary="Get Strategy Version")
async def strategy_version():
    import os
    return {
        "ok": True,
        "ALGOGPT_VERSION": os.getenv("ALGOGPT_VERSION", "unknown"),
        "STRATEGY_VERSION": os.getenv("STRATEGY_VERSION", "unknown"),
        "GIT_COMMIT": os.getenv("GIT_COMMIT", ""),
    }

@router.get("/ai", summary="AI Health")
async def ai():
    return await ai_healthcheck()


















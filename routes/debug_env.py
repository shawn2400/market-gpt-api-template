# routes/debug_env.py
import os
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["debug"])

def _mask(v: str) -> str:
    if not v: return ""
    if len(v) <= 8: return "*" * len(v)
    return v[:4] + "*" * (len(v)-8) + v[-4:]

@router.get("/debug/env")
async def debug_env():
    data = {
        "INSTANCE_ID": os.getenv("INSTANCE_ID", ""),
        "ALERTS_INGEST_HMAC_SECRET": _mask(os.getenv("ALERTS_INGEST_HMAC_SECRET","")),
        "ALERTS_INGEST_HMAC_KEY_IS_HEX": os.getenv("ALERTS_INGEST_HMAC_KEY_IS_HEX",""),
        "WEBHOOK_HMAC_SECRET": _mask(os.getenv("WEBHOOK_HMAC_SECRET","")),
    }
    return JSONResponse(data)

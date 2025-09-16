# routes/status.py
from __future__ import annotations
import time
from fastapi import APIRouter, Depends
from utils.runtime_counters import get_ws_status, get_exec_status
from utils.auth import (
    require_api_key,
    get_loaded_tokens,
    get_public_paths,
)

router = APIRouter(
    prefix="/status",
    tags=["Status"],
    dependencies=[Depends(require_api_key)],  # נפתח לציבור אם הוגדר ב-ENV
)

@router.get("/ping")
async def ping():
    return {"ok": True, "ts": int(time.time())}

@router.get("/executor")
async def executor_status():
    return {"ok": True, "status": get_exec_status()}

@router.get("/ws")
async def ws_user_status():
    return {"ok": True, "status": get_ws_status()}

@router.get("/all")
async def all_status():
    return {
        "ok": True,
        "executor": get_exec_status(),
        "ws": get_ws_status(),
    }

@router.get("/auth")
async def auth_status():
    # לא חושפים טוקנים גולמיים; רק count + מסכה + ה-allowlist הציבורי
    masked = get_loaded_tokens(mask=True)
    public = get_public_paths()
    return {
        "ok": True,
        "tokens_count": len(masked),
        "tokens": masked,
        "public": public,
    }






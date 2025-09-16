# routes/status.py
from __future__ import annotations
import time
from fastapi import APIRouter
from utils.runtime_counters import ws_user_status, exec_get_counters
from utils.auth import get_public_paths, get_loaded_tokens, refresh_tokens_from_env

# מודרני /status/...
router = APIRouter(prefix="/status", tags=["status"])

@router.get("/ping")
def ping():
    return {"ok": True, "ts": int(time.time())}

@router.get("/executor")
def status_executor():
    return {"ok": True, **exec_get_counters()}

@router.get("/ws")
def status_ws():
    return {"ok": True, **ws_user_status()}

@router.get("/all")
def status_all():
    return {
        "ok": True,
        "ping": {"ok": True, "ts": int(time.time())},
        "executor": exec_get_counters(),
        "ws_user": ws_user_status(),
        "state": "OK",
        "reasons": ["healthy"],
    }

@router.get("/auth")
def status_auth():
    masked = get_loaded_tokens(mask=True)
    return {
        "ok": True,
        "tokens_count": len(get_loaded_tokens(mask=False)),
        "tokens_preview": masked,
        "public": get_public_paths(),
    }

@router.post("/auth/refresh")
def status_auth_refresh():
    refresh_tokens_from_env()
    return status_auth()

# תאימות לנתיבים הישנים
legacy = APIRouter(tags=["status"])

@legacy.get("/executor/status")
def legacy_executor():
    return {"ok": True, "status": exec_get_counters()}

@legacy.get("/ws-user/status")
def legacy_ws_user():
    return {"ok": True, "status": ws_user_status()}










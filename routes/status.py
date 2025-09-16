# routes/status.py
from __future__ import annotations
import time
from fastapi import APIRouter
from utils.runtime_counters import get_ws_status, get_exec_status
from utils.auth import get_public_paths, get_loaded_tokens, refresh_tokens_from_env

# חדש: כל מסלולי ה"סטטוס" תחת prefix קבוע /status
router = APIRouter(prefix="/status", tags=["status"])

@router.get("/ping")
def ping():
    return {"ok": True, "ts": int(time.time())}

@router.get("/executor")
def status_executor():
    return {"ok": True, "status": get_exec_status()}

@router.get("/ws-user")
def status_ws_user():
    return {"ok": True, "status": get_ws_status()}

@router.get("/all")
def status_all():
    return {
        "ok": True,
        "ping": {"ok": True, "ts": int(time.time())},
        "executor": get_exec_status(),
        "ws_user": get_ws_status(),
    }

@router.get("/auth")
def status_auth():
    # לא חושפים טוקנים גולמיים – רק count ותצוגה ממוסכת
    masked = get_loaded_tokens(mask=True)
    return {
        "ok": True,
        "tokens_count": len(get_loaded_tokens(mask=False)),
        "tokens_preview": masked,
        "public": get_public_paths(),
    }

@router.post("/auth/refresh")
def status_auth_refresh():
    # מאפשר רענון ENV בזמן ריצה (מוגן כברירת מחדל אלא אם הוגדר כ-public)
    refresh_tokens_from_env()
    return status_auth()


# תאימות לאחור: משמרים את הנתיבים הישנים שהשתמשת בהם
legacy = APIRouter(tags=["status"])

@legacy.get("/ws-user/status")
def legacy_ws_user():
    return {"ok": True, "status": get_ws_status()}

@legacy.get("/executor/status")
def legacy_executor():
    return {"ok": True, "status": get_exec_status()}







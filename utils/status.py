# routes/status.py
from __future__ import annotations

import time
from fastapi import APIRouter

# Utils – LIVE counters (אתה כבר מחזיק אותם בקוד)
from utils.runtime_counters import (
    ws_user_status,
    exec_get_counters,
)
from utils.auth import (
    get_public_paths,
    get_loaded_tokens,
    refresh_tokens_from_env,
)


# ---------------------------------------------------------
# Router רשמי
# ---------------------------------------------------------
router = APIRouter(
    prefix="/status",
    tags=["status"]
)


# ---------------------------------------------------------
# /status/ping — בדיקה בסיסית
# ---------------------------------------------------------
@router.get("/ping", summary="Simple ping")
def ping():
    return {
        "ok": True,
        "ts": int(time.time())
    }


# ---------------------------------------------------------
# /status/executor — מצב מנוע הטריידים
# ---------------------------------------------------------
@router.get("/executor", summary="Executor engine counters")
def status_executor():
    return {
        "ok": True,
        "executor": exec_get_counters()
    }


# ---------------------------------------------------------
# /status/ws — מצב userStream / WebSocket
# ---------------------------------------------------------
@router.get("/ws", summary="WebSocket / userStream status")
def status_ws():
    return {
        "ok": True,
        "ws": ws_user_status()
    }


# ---------------------------------------------------------
# /status/all — תמונה מלאה
# ---------------------------------------------------------
@router.get("/all", summary="Full status snapshot")
def status_all():
    return {
        "ok": True,
        "timestamp": int(time.time()),
        "executor": exec_get_counters(),
        "ws_user": ws_user_status(),
        "auth": {
            "tokens_count": len(get_loaded_tokens(mask=False)),
            "tokens_preview": get_loaded_tokens(mask=True),
            "public_paths": get_public_paths(),
        },
        "state": "OK",
        "reasons": ["healthy"],
    }


# ---------------------------------------------------------
# Auth info — מצב טוקנים
# ---------------------------------------------------------
@router.get("/auth", summary="Authentication tokens status")
def status_auth():
    return {
        "ok": True,
        "tokens_count": len(get_loaded_tokens(mask=False)),
        "tokens_preview": get_loaded_tokens(mask=True),
        "public_paths": get_public_paths(),
    }


# ---------------------------------------------------------
# Auth refresh — רענון טוקנים מהסביבה
# ---------------------------------------------------------
@router.post("/auth/refresh", summary="Reload tokens from environment")
def status_auth_refresh():
    refresh_tokens_from_env()
    return status_auth()


# ---------------------------------------------------------
# /status (root) — תאימות / פינג קצר
# ---------------------------------------------------------
@router.get("", summary="Root status")
@router.get("/", summary="Root status")
def status_root():
    return {
        "ok": True,
        "ts": int(time.time()),
        "hint": "For full info: /status/all",
        "endpoints": [
            "/status/ping",
            "/status/executor",
            "/status/ws",
            "/status/all",
            "/status/auth",
        ],
    }


# ---------------------------------------------------------
# Legacy compatibility — נתיבים ישנים
# ---------------------------------------------------------
legacy = APIRouter(tags=["status"])


@legacy.get("/executor/status", summary="Legacy executor status")
def legacy_executor():
    return {
        "ok": True,
        "status": exec_get_counters()
    }


@legacy.get("/ws-user/status", summary="Legacy ws-user status")
def legacy_ws_user():
    return {
        "ok": True,
        "status": ws_user_status()
    }


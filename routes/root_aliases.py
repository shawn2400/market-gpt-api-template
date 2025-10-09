# routes/root_aliases.py
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header

# נשען על המימושים הקיימים במסלולי position_ops
from routes.position_ops import (
    be as _pos_be,
    trail as _pos_trail,
    tp_ladder as _pos_tp_ladder,
    tp_cancel as _pos_tp_cancel,
    tp_one as _pos_tp_one,
    close_fraction as _pos_close_fraction,
    close_percent_alias as _pos_close_percent,
    manage_once as _pos_manage_once,
)

router = APIRouter(tags=["aliases"])

# שמירה על אחידות ה-OK/ERR
def _ok(**data) -> Dict[str, Any]:
    d = {"ok": True}
    d.update(data)
    return d

def _err(reason: str, **data) -> Dict[str, Any]:
    d = {"ok": False, "reason": reason}
    d.update(data)
    return d

# הרשאת Bearer רכה (כמו ב-position_ops)
API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()

def _auth_ok(auth_header: Optional[str]) -> bool:
    if not API_BEARER_TOKEN:
        return True
    if not auth_header or not auth_header.startswith("Bearer "):
        return False
    return (auth_header.split(" ", 1)[1].strip() == API_BEARER_TOKEN)

# =============== אליאסים ברוט ===========
# כל האליאסים פשוט מעבירים הלאה לפונקציה המקורית ושומרים על
# Auth + Anti-Replay באמצעות הפרמטרים המועברים (headers+body)

@router.post("/manage-once", summary="[ALIAS] Delegates to /position-ops/manage-once")
def manage_once_alias(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    # בחרת להשתמש בשורש במסמכים/סקריפטים – האליאס יקרא למסלול המקורי
    return _pos_manage_once(
        payload=payload,
        Authorization=Authorization,
        x_timestamp=x_timestamp,
        x_nonce=x_nonce,
        x_signature=x_signature,
    )

@router.post("/be", summary="[ALIAS] Delegates to /position-ops/be")
def be_alias(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return _pos_be(payload=payload, Authorization=Authorization,
                   x_timestamp=x_timestamp, x_nonce=x_nonce, x_signature=x_signature)

@router.post("/trail", summary="[ALIAS] Delegates to /position-ops/trail")
def trail_alias(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return _pos_trail(payload=payload, Authorization=Authorization,
                      x_timestamp=x_timestamp, x_nonce=x_nonce, x_signature=x_signature)

@router.post("/tp/ladder", summary="[ALIAS] Delegates to /position-ops/tp/ladder")
def tp_ladder_alias(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return _pos_tp_ladder(payload=payload, Authorization=Authorization,
                          x_timestamp=x_timestamp, x_nonce=x_nonce, x_signature=x_signature)

@router.post("/tp/one", summary="[ALIAS] Delegates to /position-ops/tp/one")
def tp_one_alias(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return _pos_tp_one(payload=payload, Authorization=Authorization,
                       x_timestamp=x_timestamp, x_nonce=x_nonce, x_signature=x_signature)

@router.post("/tp/cancel", summary="[ALIAS] Delegates to /position-ops/tp/cancel")
def tp_cancel_alias(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return _pos_tp_cancel(payload=payload, Authorization=Authorization,
                          x_timestamp=x_timestamp, x_nonce=x_nonce, x_signature=x_signature)

@router.post("/close", summary="[ALIAS] Delegates to /position-ops/close")
def close_alias(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return _pos_close_fraction(payload=payload, Authorization=Authorization,
                               x_timestamp=x_timestamp, x_nonce=x_nonce, x_signature=x_signature)

@router.post("/close-percent", summary="[ALIAS] Delegates to /position-ops/close-percent")
def close_percent_alias(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return _pos_close_percent(payload=payload, Authorization=Authorization,
                              x_timestamp=x_timestamp, x_nonce=x_nonce, x_signature=x_signature)

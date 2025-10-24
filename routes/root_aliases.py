# routes/root_aliases.py
from __future__ import annotations

import inspect
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header

# נשען על המימושים ב-position_ops (ייבוא מדוייק לפי שמות הפונקציות האמיתיים)
from routes.position_ops import (
    place_be as _pos_be,
    place_trailing as _pos_trail,
    place_tp_ladder as _pos_tp_ladder,
    cancel_tp as _pos_tp_cancel,
    place_tp_one as _pos_tp_one,
    close_fraction as _pos_close_fraction,
    close_percent_alias as _pos_close_percent,
    manage_once as _pos_manage_once,
)

router = APIRouter(tags=["aliases"])

async def _delegate(handler, **kwargs):
    """
    מפעיל את ה-handler ותומך גם בסינכרוני וגם באסינכרוני.
    """
    res = handler(**kwargs)
    if inspect.isawaitable(res):
        return await res
    return res

# =============== אליאסים ברוט ===============
@router.post("/manage-once", summary="[ALIAS] Delegates to /position-ops/manage-once")
async def manage_once_alias(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return await _delegate(
        _pos_manage_once,
        request=None,  # לא דרוש בפועל במימוש הנוכחי
        payload=payload,
        authorization=authorization,
    )

@router.post("/be", summary="[ALIAS] Delegates to /position-ops/be")
async def be_alias(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return await _delegate(
        _pos_be,
        request=None,
        payload=payload,
        authorization=authorization,
        x_timestamp=x_timestamp,
        x_nonce=x_nonce,
        x_signature=x_signature,
    )

@router.post("/trail", summary="[ALIAS] Delegates to /position-ops/trail")
async def trail_alias(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return await _delegate(
        _pos_trail,
        request=None,
        payload=payload,
        authorization=authorization,
        x_timestamp=x_timestamp,
        x_nonce=x_nonce,
        x_signature=x_signature,
    )

@router.post("/tp/ladder", summary="[ALIAS] Delegates to /position-ops/tp/ladder")
async def tp_ladder_alias(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return await _delegate(
        _pos_tp_ladder,
        payload=payload,
        authorization=authorization,
    )

@router.post("/tp/one", summary="[ALIAS] Delegates to /position-ops/tp/one")
async def tp_one_alias(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return await _delegate(
        _pos_tp_one,
        payload=payload,
        authorization=authorization,
    )

@router.post("/tp/cancel", summary="[ALIAS] Delegates to /position-ops/tp/cancel")
async def tp_cancel_alias(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return await _delegate(
        _pos_tp_cancel,
        payload=payload,
        authorization=authorization,
    )

@router.post("/close", summary="[ALIAS] Delegates to /position-ops/close (fraction)")
async def close_alias(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return await _delegate(
        _pos_close_fraction,
        payload=payload,
        authorization=authorization,
    )

@router.post("/close-percent", summary="[ALIAS] Delegates to /position-ops/close-percent")
async def close_percent_alias(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    return await _delegate(
        _pos_close_percent,
        payload=payload,
        authorization=authorization,
    )


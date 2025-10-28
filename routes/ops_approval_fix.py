# -*- coding: utf-8 -*-
from __future__ import annotations
import os, hmac, time, uuid
from typing import Literal, List, Optional, Dict, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, Header, HTTPException

router = APIRouter(prefix="/ops", tags=["ops-approval"])
_API_BEARER = os.getenv("API_BEARER_TOKEN", "")

def _require_bearer_local(authorization: Optional[str]) -> None:
    if not _API_BEARER:
        raise HTTPException(status_code=503, detail="API_BEARER_TOKEN missing")
    if not authorization or " " not in authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")
    scheme, token = authorization.split(" ", 1)
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        ok = hmac.compare_digest(token.strip(), _API_BEARER)
    except Exception:
        ok = (token.strip() == _API_BEARER)
    if not ok:
        raise HTTPException(status_code=401, detail="Unauthorized")

Side = Literal["BUY","SELL"]
Mode = Literal["futures","spot"]

class ApprovalRequest(BaseModel):
    symbol: str = Field(..., min_length=3, max_length=20)
    side: Side
    mode: Mode = "futures"
    budget: Optional[float] = Field(None, ge=0)
    entry_type: Optional[str] = None
    reason: Optional[str] = None
    tp_atr_mult: Optional[List[float]] = None
    sl_atr_mult: Optional[float] = None
    leverage: Optional[int] = Field(None, ge=1, le=125)

class ApprovalTicket(BaseModel):
    ok: bool = True
    ts: int = Field(default_factory=lambda: int(time.time()))
    ticket_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request: Dict[str, Any]

@router.post("/approval", response_model=ApprovalTicket)
def ops_approval(body: ApprovalRequest, authorization: Optional[str] = Header(default=None, alias="Authorization")):
    _require_bearer_local(authorization)
    return ApprovalTicket(request=body.model_dump())

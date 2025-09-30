# routes/trade_approvals.py
from __future__ import annotations
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, Query
from utils.auth import require_api_key

logger = logging.getLogger("algogpt.routes.trade_approvals")

router = APIRouter(prefix="/trade", tags=["Trades"], dependencies=[Depends(require_api_key)])

try:
    from utils.approvals import ConfirmStore
except Exception:
    class ConfirmStore:  # type: ignore
        @staticmethod
        def get(_idem: str) -> Optional[Dict[str, Any]]: return None
        @staticmethod
        def approve(_idem: str, approver: Optional[str] = None) -> Dict[str, Any]: return {"ok":False,"error":"unavailable"}
        @staticmethod
        def reject(_idem: str, approver: Optional[str] = None) -> Dict[str, Any]: return {"ok":False,"error":"unavailable"}
        @staticmethod
        async def run(_idem: str) -> Dict[str, Any]: return {"ok":False,"error":"trade executor missing"}

@router.get("/approve")
async def trade_approve(id: str = Query(..., min_length=8, max_length=64)) -> Dict[str, Any]:
    rec = ConfirmStore.get(id)
    if not rec:
        return {"ok": False, "error": "not_found_or_expired"}
    a = ConfirmStore.approve(id, approver="http")
    if not a.get("ok"):
        return {"ok": False, "error": a.get("error","not_approved")}
    run_res = await ConfirmStore.run(id)
    return {"ok": bool(run_res.get("ok")), "result": run_res.get("result"), "error": run_res.get("error")}

@router.get("/reject")
async def trade_reject(id: str = Query(..., min_length=8, max_length=64)) -> Dict[str, Any]:
    rec = ConfirmStore.get(id)
    if not rec:
        return {"ok": False, "error": "not_found_or_expired"}
    r = ConfirmStore.reject(id, approver="http")
    return {"ok": bool(r.get("ok")), "rejected": True if r.get("ok") else False, "error": r.get("error")}

@router.get("/ticket")
async def trade_ticket(id: str = Query(..., min_length=8, max_length=64)) -> Dict[str, Any]:
    rec = ConfirmStore.get(id)
    if not rec:
        return {"ok": False, "error": "not_found_or_expired"}
    return {"ok": True, "ticket": rec}


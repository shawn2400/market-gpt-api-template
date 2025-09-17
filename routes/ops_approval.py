from __future__ import annotations
import time
from typing import Dict, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from routes.trade import _PENDING as PENDING, execute_real_trade, TradeRequest

router = APIRouter(tags=["ops-approval"])

def _html(msg: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><meta charset='utf-8'>"
                        f"<body style='font-family:sans-serif;max-width:560px;margin:3rem auto'>"
                        f"<h2>{msg}</h2></body>")

@router.get("/ops/approve")
def approve(aid: str, tok: str):
    rec = PENDING.get(aid)
    now = time.time()
    if not rec or rec.get("token") != tok:
        raise HTTPException(status_code=404, detail="Invalid approval link")
    if rec.get("expires", 0) < now:
        PENDING.pop(aid, None)
        raise HTTPException(status_code=410, detail="Approval link expired")

    # שלוף בקשה ותוצאה משוערת
    req_dict = rec.get("req") or {}
    preview  = rec.get("preview") or {}
    PENDING.pop(aid, None)

    # ביצוע אמיתי
    req = TradeRequest.model_validate(req_dict)
    req.dry_run = False  # מוודאים ביצוע אמיתי
    exec_info = execute_real_trade(req, preview)

    return _html("✅ Approved! Order executed on Binance Futures.")

@router.get("/ops/reject")
def reject(aid: str, tok: str):
    rec = PENDING.get(aid)
    if not rec or rec.get("token") != tok:
        raise HTTPException(status_code=404, detail="Invalid approval link")
    PENDING.pop(aid, None)
    return _html("❌ Rejected. Order cancelled.")


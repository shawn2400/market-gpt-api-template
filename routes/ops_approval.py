# routes/ops_approval.py
from __future__ import annotations
import time
from typing import Dict, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

# מסונכרן לשמות שהוגדרו ב-routes.trade
from routes.trade import _PENDING as PENDING, TradeRequest, execute_real_trade

router = APIRouter(tags=["ops-approval"])

def _html(msg: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:560px;margin:3rem auto'>"
        f"<h2>{msg}</h2></body>"
    )

@router.get("/ops/approve")
def approve(id: str):
    rec = PENDING.get(id)
    now = time.time()
    if not rec:
        raise HTTPException(status_code=404, detail="Invalid or expired approval id")
    # TTL
    if (now - float(rec.get("ts", 0))) > 60 * 5:
        PENDING.pop(id, None)
        raise HTTPException(status_code=410, detail="Approval link expired")

    # שלוף בקשה ובצע בפועל
    req_dict: Dict[str, Any] = rec.get("req") or {}
    PENDING.pop(id, None)
    req = TradeRequest.model_validate(req_dict)
    req.dry_run = False
    execute_real_trade(req, preview=None)
    return _html("✅ Approved! Order executed on Binance Futures.")

@router.get("/ops/reject")
def reject(id: str):
    rec = PENDING.get(id)
    if not rec:
        raise HTTPException(status_code=404, detail="Invalid or expired approval id")
    PENDING.pop(id, None)
    return _html("❌ Rejected. Order cancelled.")




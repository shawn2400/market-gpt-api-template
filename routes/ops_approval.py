from __future__ import annotations
import time
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

# נשתף את ה-PENDING מ-routes.trade
try:
    from routes.trade import _PENDING as PENDING, _build_result as build_result
except Exception:
    PENDING: Dict[str, Dict[str, Any]] = {}
    def build_result(req): return {"ok": True}

router = APIRouter(tags=["ops-approval"])

def _html(msg: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><meta charset='utf-8'><body style='font-family:sans-serif'><h2>{msg}</h2></body>")

@router.get("/ops/approve")
def approve(aid: str, tok: str):
    rec = PENDING.get(aid)
    now = time.time()
    if not rec or rec.get("token") != tok:
        raise HTTPException(status_code=404, detail="Invalid approval link")
    if rec.get("expires", 0) < now:
        PENDING.pop(aid, None)
        raise HTTPException(status_code=410, detail="Approval link expired")
    PENDING.pop(aid, None)

    # כאן הייתם מבצעים את ההוראה בפועל; כרגע נחזיר JSON עם ה-result שבנינו מראש
    result = rec.get("result") or {}
    return _html("✅ Approved! Order will be executed (or simulated).")

@router.get("/ops/reject")
def reject(aid: str, tok: str):
    rec = PENDING.get(aid)
    now = time.time()
    if not rec or rec.get("token") != tok:
        raise HTTPException(status_code=404, detail="Invalid approval link")
    PENDING.pop(aid, None)
    return _html("❌ Rejected. Order cancelled.")

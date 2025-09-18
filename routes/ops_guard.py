# routes/ops_guard.py
from __future__ import annotations
import os, hmac, hashlib, time
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/ops", tags=["Ops"])

OPS_SIGN_SECRET = (os.getenv("OPS_SIGN_SECRET") or "ops_local_secret").encode()

def _verify(symbol: str, tf: str, side: str, score: float, exp: int, sig: str) -> None:
    if int(exp) < int(time.time()):
        raise HTTPException(status_code=400, detail="Expired: ההודעה פגה, נא לסרוק מחדש")
    base = f"{symbol}|{tf}|{side}|{score}|{exp}"
    expect = hmac.new(OPS_SIGN_SECRET, base.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expect, sig):
        raise HTTPException(status_code=400, detail="Invalid signature")

@router.get("/approve")
async def approve(symbol: str, side: str, tf: str, score: float,
                  src: str = "scan", exp: int = Query(...), sig: str = Query(...)):
    _verify(symbol, tf, side, score, exp, sig)
    # TODO: בצע את הפעולה בפועל (פתיחת פוזיציה)
    return {"ok": True, "action": "approved", "symbol": symbol, "side": side, "tf": tf}

@router.get("/reject")
async def reject(symbol: str, side: str, tf: str, score: float,
                 src: str = "scan", exp: int = Query(...), sig: str = Query(...)):
    _verify(symbol, tf, side, score, exp, sig)
    # TODO: ביטול/ניקוי תור
    return {"ok": True, "action": "rejected", "symbol": symbol, "side": side, "tf": tf}

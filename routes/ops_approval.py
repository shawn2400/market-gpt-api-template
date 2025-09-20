# routes/ops_approval.py
from __future__ import annotations
import os, time, hmac, hashlib
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

# נשתמש במאגר ה-PENDING של routes.trade (איפוס אחרי פעולה)
from routes.trade import _PENDING as PENDING, TradeReq  # type: ignore

try:
    from utils.trade_executor import execute_trade_live  # type: ignore
except Exception:
    execute_trade_live = None  # type: ignore

router = APIRouter(tags=["ops-approval"])

def _html(msg: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:560px;margin:3rem auto'>"
        f"<h2>{msg}</h2></body>"
    )

# ===== חתימה/טוקן לאימות קישורי אישור =====
_SIGN_SECRET = (os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET") or "").encode("utf-8")

def _verify_sig(ticket_id: str, expires: Optional[int], sig: Optional[str]) -> bool:
    if not (_SIGN_SECRET and ticket_id and expires and sig):
        return False
    try:
        msg = f"{ticket_id}:{int(expires)}".encode("utf-8")
        want = hmac.new(_SIGN_SECRET, msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest((sig or "").strip().lower(), want)
    except Exception:
        return False

def _get_pending(aid: str) -> Dict[str, Any]:
    rec = PENDING.get(aid)
    if not rec:
        raise HTTPException(status_code=404, detail="Approval not found or expired")
    return rec

# ===== /ops/approve — ציבורי (נחתם) =====
@router.get("/ops/approve")
async def approve(
    ticket_id: str | None = None,
    id: str | None = None,
    aid: str | None = None,
    expires: Optional[int] = None,
    sig: Optional[str] = None,
    tok: Optional[str] = None,
):
    """URL מאובטח לאישור טריידים: תומך גם ב-token ישן וגם ב-sig+expires."""
    key = ticket_id or id or aid
    if not key:
        raise HTTPException(status_code=400, detail="missing ticket id")

    rec = _get_pending(key)
    now = time.time()

    # תמיכה לאחור: token פנימי (אם נשמר), אחרת חתימה
    token_ok = bool(tok and rec.get("token") and tok == rec.get("token"))
    sig_ok   = _verify_sig(key, expires, sig) and (expires is not None and now <= float(expires))
    if not (token_ok or sig_ok):
        raise HTTPException(status_code=401, detail="invalid or expired approval link")

    req_dict = rec.get("req") or {}
    PENDING.pop(key, None)  # אין שיחזור כפול

    if execute_trade_live is None:
        return _html("⚠️ Executor unavailable at the moment.")

    # העברה לביצוע אמיתי
    try:
        req = TradeReq.model_validate(req_dict)  # type: ignore
        req.dry_run = False
        res = await execute_trade_live(
            symbol=req.symbol,
            side=req.side,
            leverage=int(req.leverage),
            budget=float(req.budget_usd),
            dry_run=False,
            entry=(float(req.entry) if (req.entry is not None and float(req.entry) > 0) else None),
            sl=None,
            tp=None,
            tp_targets=(req.tp_targets if req.tp_targets else None),
            confirm_first=False,
            telegram_chat_id=None,
        )
        ok = bool(res and res.get("ok", False))
        return _html("✅ Approved & executed." if ok else "⚠️ Approved, but execution reported an issue.")
    except Exception as e:
        return _html(f"❌ Execution failed: {e}")

# ===== /ops/reject — ציבורי (נחתם) =====
@router.get("/ops/reject")
def reject(
    ticket_id: str | None = None,
    id: str | None = None,
    aid: str | None = None,
    expires: Optional[int] = None,
    sig: Optional[str] = None,
    tok: Optional[str] = None,
):
    key = ticket_id or id or aid
    if not key:
        raise HTTPException(status_code=400, detail="missing ticket id")

    rec = _get_pending(key)
    now = time.time()

    token_ok = bool(tok and rec.get("token") and tok == rec.get("token"))
    sig_ok   = _verify_sig(key, expires, sig) and (expires is not None and now <= float(expires))
    if not (token_ok or sig_ok):
        raise HTTPException(status_code=401, detail="invalid or expired rejection link")

    PENDING.pop(key, None)
    return _html("❌ Rejected. Order cancelled.")



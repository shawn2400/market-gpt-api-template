# routes/ops_approve.py
from __future__ import annotations
from typing import Optional, Dict, Any
import os
import time
import hmac
import hashlib
import httpx
from fastapi import APIRouter, Query, Request, Header
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/ops", tags=["Ops"])

# ⚙️ קריאה פנימית אל /grid/trade
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "").rstrip("/")
INTERNAL_TOKEN = os.getenv("OPS_INTERNAL_TOKEN") or os.getenv("API_TOKEN") or os.getenv("TOKEN")

def _bool(x: Optional[str | bool]) -> Optional[bool]:
    if isinstance(x, bool):
        return x
    if x is None:
        return None
    s = str(x).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return None

async def _post_grid_trade(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not PUBLIC_HOST:
        return {"ok": False, "error": "PUBLIC_HOST not set"}
    if not INTERNAL_TOKEN:
        return {"ok": False, "error": "OPS_INTERNAL_TOKEN not set"}
    url = f"{PUBLIC_HOST}/grid/trade"
    headers = {"Authorization": f"Bearer {INTERNAL_TOKEN}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(url, headers=headers, json=payload)
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"text": r.text}
            return {"ok": r.status_code < 400, "status": r.status_code, "response": data}
    except Exception as e:
        return {"ok": False, "error": f"http_error: {e}"}

@router.get("/approve", summary="Approve trade from Telegram/ops and trigger grid/trade")
async def ops_approve(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    side: str = Query(..., description="BUY/SELL for spot or LONG/SHORT for futures"),
    # אופציונלי: מטא־דטה מהסריקה
    tf: Optional[str] = Query("15m", description="timeframe"),
    score: Optional[float] = Query(None),
    src: Optional[str] = Query("scan"),
    chat_id: Optional[str] = Query(None),
    # פרמטרים למסחר
    market: str = Query("futures", description="futures|spot"),
    account_id: str = Query("main"),
    budget: float = Query(10.0),
    leverage: Optional[int] = Query(10),
    grids: int = Query(3),
    dry_run: Optional[bool] = Query(True),
) -> Dict[str, Any]:
    """
    מאשר טרייד ומטריגר grid/trade פנימי עם הטוקן של השרת.
    נתיב ציבורי (לפי המידלוואר), לא דורש API key מהקליינט.
    """
    payload: Dict[str, Any] = {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "budget": float(budget),
        "grids": int(grids),
        "dry_run": bool(_bool(dry_run) if dry_run is not None else True),
        "market": market.lower(),
        "account_id": account_id,
        "meta": {
            "source": src or "ops",
            "timeframe": tf,
            "score": score,
            "approved_via": "GET /ops/approve",
            "ts": int(time.time()),
            "chat_id": chat_id,
        },
    }
    if leverage is not None:
        payload["leverage"] = int(leverage)

    result = await _post_grid_trade(payload)
    return {
        "ok": bool(result.get("ok")),
        "action": "approve",
        "symbol": symbol.upper(),
        "side": side.upper(),
        "market": market.lower(),
        "request": payload,
        "result": result,
    }

@router.get("/reject", summary="Reject trade (no-op, with audit echo)")
async def ops_reject(
    symbol: str = Query(...),
    side: str = Query(...),
    tf: Optional[str] = Query("15m"),
    score: Optional[float] = Query(None),
    src: Optional[str] = Query("scan"),
    chat_id: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """דחיית טרייד (ללא פעולה למסחר) — מחזיר אקו לטובת לוג/טלגרם."""
    return {
        "ok": True,
        "action": "reject",
        "symbol": symbol.upper(),
        "side": side.upper(),
        "meta": {"source": src, "timeframe": tf, "score": score, "chat_id": chat_id, "ts": int(time.time())},
    }

# ---------- Signed approve ----------
_SIGN_SECRET = (os.getenv("OPS_SIGN_SECRET", "") or os.getenv("WEBHOOK_HMAC_SECRET", "")).strip()

def _hmac_valid(raw: bytes, sig_hex: str) -> bool:
    if not _SIGN_SECRET:
        return False
    try:
        mac = hmac.new(_SIGN_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(mac, (sig_hex or "").strip().lower())
    except Exception:
        return False

@router.post("/approve/signed", summary="Approve via signed HMAC (body) and trigger grid/trade")
async def ops_approve_signed(
    request: Request,
    x_signature: str = Header(default=""),  # ✅ בלי convert_underscores=False → מאפשר 'X-Signature'
):
    """
    הגוף נחתם מול OPS_SIGN_SECRET (או WEBHOOK_HMAC_SECRET).
    דוגמה לגוף:
    {"action":"approve","ticket_id":"T1","symbol":"BTCUSDT","side":"BUY","qty":0.001,"price":null,"lev":10,"position_side":"BOTH","budget":null}
    """
    raw = await request.body()
    if not _hmac_valid(raw, x_signature):
        return JSONResponse(status_code=401, content={"detail": "Bad signature"})

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Bad JSON"})

    action = str(body.get("action") or "approve").lower()
    if action != "approve":
        return JSONResponse(status_code=400, content={"detail": "unsupported action"})

    symbol = str(body.get("symbol") or "").upper()
    side   = str(body.get("side") or "").upper()
    qty    = body.get("qty")
    budget = body.get("budget")
    lev    = body.get("lev") or body.get("leverage") or 10
    position_side = (body.get("position_side") or "BOTH").upper()

    if not symbol or side not in {"BUY","SELL","LONG","SHORT"}:
        return JSONResponse(status_code=400, content={"detail": "invalid symbol/side"})

    req_payload: Dict[str, Any] = {
        "symbol": symbol,
        "side": "BUY" if side in ("BUY", "LONG") else "SELL",
        "leverage": int(lev),
        "dry_run": False,
        "market": "futures",
        "meta": {
            "approved_via": "POST /ops/approve/signed",
            "position_side": position_side,
            "ticket_id": body.get("ticket_id"),
            "ts": int(time.time()),
        }
    }
    if qty is not None:
        req_payload["quantity"] = float(qty)
    if budget is not None:
        req_payload["budget"] = float(budget)

    result = await _post_grid_trade(req_payload)
    return {
        "ok": bool(result.get("ok")),
        "request": req_payload,
        "result": result,
    }

__all__ = ["router"]







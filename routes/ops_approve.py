# routes/ops_approve.py
from __future__ import annotations
from typing import Optional, Dict, Any
import os
import time
import hmac
import hashlib
import json

import httpx
from fastapi import APIRouter, Query, Request, Header, HTTPException

from utils.trade_executor import execute_trade_live  # <- לשימוש בנתיב החתום

router = APIRouter(prefix="/ops", tags=["Ops"])

# ⚙️ קריאה פנימית אל /grid/trade
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "").rstrip("/")
INTERNAL_TOKEN = os.getenv("OPS_INTERNAL_TOKEN") or os.getenv("API_TOKEN") or os.getenv("TOKEN")

# 🔐 חתימה
OPS_SIGN_SECRET = (os.getenv("OPS_SIGN_SECRET", "") or os.getenv("WEBHOOK_HMAC_SECRET", "")).strip()
API_TOKEN = (os.getenv("API_TOKEN", "") or os.getenv("API_BEARER_TOKEN", "")).strip()

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
            data = r.json() if r.headers.get("content-type","").startswith("application/json") else {"text": r.text}
            return {"ok": r.status_code < 400, "status": r.status_code, "response": data}
    except Exception as e:
        return {"ok": False, "error": f"http_error: {e}"}

def _verify_hmac(body: bytes, sig_hex: str) -> bool:
    if not OPS_SIGN_SECRET or not sig_hex:
        return False
    mac = hmac.new(OPS_SIGN_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, sig_hex.lower())

def _verify_api_key(x_api_key: str | None) -> None:
    if not API_TOKEN:
        return
    if not x_api_key or x_api_key.strip() != API_TOKEN:
        # אם יש לך מידלוואר שמוודא API Key — אפשר להוריד את זה.
        raise HTTPException(status_code=401, detail="Invalid API key")

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
        # שדות עזר (לא מזיקים אם /grid/trade מתעלם מהם)
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
    """
    דחיית טרייד (ללא פעולה למסחר) — מחזיר אקו לטובת לוג/טלגרם.
    """
    return {
        "ok": True,
        "action": "reject",
        "symbol": symbol.upper(),
        "side": side.upper(),
        "meta": {"source": src, "timeframe": tf, "score": score, "chat_id": chat_id, "ts": int(time.time())},
    }

# ✅ נתיב חתום שמבצע טרייד עם ה-executor (MARKET/HYBRID לפי ההגדרות שלך)
@router.post("/approve/signed", include_in_schema=False, tags=["ops"])
async def approve_signed(
    request: Request,
    x_signature: str = Header(default=""),
    x_api_key: str | None = Header(default=None),
):
    """
    גוף JSON לדוגמה:
    {
      "action": "approve",
      "ticket_id": "T1",
      "symbol": "BTCUSDT",
      "side": "BUY",
      "qty": 0.001,                 # אופציונלי אם שולחים budget
      "budget": null,               # אופציונלי אם שולחים qty
      "price": null,                # anchor אופציונלי
      "lev": 10,                    # אופציונלי (אם חסר – דינמי/ברירת מחדל)
      "position_side": "BOTH"       # BOTH/LONG/SHORT
    }
    הכותרות:
      X-Signature = hex(hmac_sha256(body, OPS_SIGN_SECRET))
      X-API-Key   = ${API_TOKEN}    (אם קיים מידלוואר אפשר לוותר, פה זה וולונטרי)
    """
    body = await request.body()
    # אימות API key (וולונטרי אם כבר יש מידלוואר)
    try:
        _verify_api_key(x_api_key)
    except HTTPException:
        # אם יש לך נתיבים פומביים תחת /ops — תוכל לבטל את הוולידציה הזו.
        raise

    if not _verify_hmac(body, x_signature):
        raise HTTPException(status_code=401, detail="Bad signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="bad json")

    if str(payload.get("action", "")).lower() != "approve":
        raise HTTPException(status_code=400, detail="bad action")

    symbol = str(payload["symbol"]).upper()
    side   = str(payload["side"]).upper()
    qty_raw = payload.get("qty")
    qty = float(qty_raw) if (qty_raw is not None and str(qty_raw).strip() != "") else None
    lev = payload.get("lev")
    budget = payload.get("budget")
    entry  = payload.get("price")
    pos_side = payload.get("position_side") or "BOTH"

    leverage = int(lev) if lev is not None else int(float(os.getenv("MIN_LEVERAGE", "5")))
    chat_id_env = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")

    res = await execute_trade_live(
        symbol, side,
        budget=budget,
        leverage=leverage,
        dry_run=False,
        quantity=qty,
        entry=entry,
        confirm_first=False,            # אישור כבר נעשה – זה נתיב החתימה
        telegram_chat_id=chat_id_env,
        position_side=pos_side,
    )
    ok = bool(res.get("ok"))
    return {"ok": ok, "executed": res}

__all__ = ["router"]



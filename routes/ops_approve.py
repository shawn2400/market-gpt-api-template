# routes/ops_approve.py
from __future__ import annotations
import os, hmac, hashlib, base64, time, json
from typing import Optional, Literal
from fastapi import APIRouter, Request, Header, Query
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

router = APIRouter()

def _secret_bytes() -> bytes:
    raw = os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET") or ""
    s = raw.strip()
    if len(s) == 64:
        try:
            return bytes.fromhex(s)
        except Exception:
            pass
    return s.encode("utf-8")

def _hmac_hex(body: bytes, secret: bytes) -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()

def _eq_sig(provided: str, expected_hex: str) -> bool:
    """
    תומך גם ב־HEX וגם בבסיס־64 וגם ב־'sha256=<hex>'.
    """
    p = (provided or "").strip()
    if p.lower().startswith("sha256="):
        p = p.split("=", 1)[1].strip()
    try:
        # אם זה Base64 – נהפוך ל-hex להשוואה
        maybe_b = base64.b64decode(p, validate=True)
        p_hex = maybe_b.hex()
    except Exception:
        p_hex = p.lower()
    try:
        return hmac.compare_digest(p_hex, expected_hex.lower())
    except Exception:
        return p_hex == expected_hex.lower()

# -------- Signed POST (RAW body HMAC) --------
class SignedApproveBody(BaseModel):
    action: Literal["approve"]
    ticket_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: float
    price: Optional[float] = None
    lev: int = Field(..., alias="lev")
    position_side: Literal["BOTH", "LONG", "SHORT"] = "BOTH"
    budget: float

@router.post("/ops/approve/signed")
async def ops_approve_signed(
    request: Request,
    x_signature: Optional[str] = Header(default=None, convert_underscores=False),
):
    secret = _secret_bytes()
    body = await request.body()
    expected = _hmac_hex(body, secret)

    if not x_signature or not _eq_sig(x_signature, expected):
        return JSONResponse({"detail": "Bad signature"}, status_code=400)

    try:
        data = SignedApproveBody.model_validate_json(body)
    except Exception as e:
        return JSONResponse({"detail": f"Invalid body: {e}"}, status_code=422)

    # בשלב זה החתימה תקינה והגוף חוקי — מחזירים ACK.
    # אם יש לך Executor פנימי – קרא כאן לפונקציה שמבצעת בפועל.
    return JSONResponse({
        "ok": True,
        "ack": "approved",
        "ticket_id": data.ticket_id,
        "symbol": data.symbol,
        "side": data.side,
        "qty": data.qty,
        "lev": data.lev,
        "position_side": data.position_side,
        "budget": data.budget,
    })

# -------- GET (Query HMAC) — אופציונלי לשמירה על תאימות --------
@router.get("/ops/approve")
async def ops_approve_query(
    ticket_id: str = Query(...),
    symbol: str = Query(...),
    side: Literal["BUY", "SELL"] = Query(...),
    qty: float = Query(...),
    market: str = Query("futures"),
    budget: float = Query(...),
    leverage: int = Query(...),
    ts_ms: int = Query(...),
    sig: str = Query(...),
):
    """
    פורמט חתימה מומלץ: HMAC על מחרוזת canonical, למשל:
    f"ticket_id={ticket_id}&symbol={symbol}&side={side}&qty={qty}&market={market}&budget={budget}&leverage={leverage}&ts_ms={ts_ms}"
    """
    secret = _secret_bytes()
    msg = (
        f"ticket_id={ticket_id}&symbol={symbol}&side={side}&qty={qty}&"
        f"market={market}&budget={budget}&leverage={leverage}&ts_ms={ts_ms}"
    ).encode("utf-8")
    expected = _hmac_hex(msg, secret)

    # הגנה בסיסית מפני שחזור
    now_ms = int(time.time() * 1000)
    if abs(now_ms - ts_ms) > 120_000:  # 2 דקות
        return JSONResponse({"detail": "ts_ms out of window"}, status_code=400)

    if not _eq_sig(sig, expected):
        return JSONResponse({"detail": "Bad signature"}, status_code=400)

    return JSONResponse({
        "ok": True,
        "ack": "approved",
        "ticket_id": ticket_id,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "leverage": leverage,
        "budget": budget,
        "ts_ms": ts_ms,
    })







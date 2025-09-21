# routes/ops_approve.py
from __future__ import annotations
import os, json, time, hmac, hashlib, httpx, secrets
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Body, Query
from fastapi.responses import HTMLResponse

# Redis (async)
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

router = APIRouter(tags=["ops-approval"])

# -------------------- CFG --------------------
NS            = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL     = os.getenv("REDIS_URL", "")
PUBLIC_HOST   = (os.getenv("PUBLIC_HOST") or os.getenv("WEBHOOK_HOST") or "").strip()
HMAC_SECRET   = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()
ADMIN_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID")
TICKET_TTL_SEC = int(os.getenv("OPS_TICKET_TTL_SEC", "1800"))  # 30 דקות

def KEY_TICKET(tid: str) -> str:
    return f"{NS}:ticket:{tid}"

# -------------------- utils --------------------
def _html(msg: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:560px;margin:3rem auto'>"
        f"<h2>{msg}</h2></body>"
    )

async def _redis():
    if not aioredis:
        raise HTTPException(status_code=500, detail="redis.asyncio not available")
    if not REDIS_URL:
        raise HTTPException(status_code=500, detail="REDIS_URL not set")
    return aioredis.from_url(REDIS_URL, decode_responses=True)

def _expired(ts: float, ttl_sec: int = TICKET_TTL_SEC) -> bool:
    try:
        return (time.time() - float(ts)) > ttl_sec
    except Exception:
        return True

def _sign_hex(secret_hex: str, payload: bytes) -> str:
    key = bytes.fromhex(secret_hex) if len(secret_hex) == 64 else secret_hex.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

async def _execute_via_signed_endpoint(body: Dict[str, Any]) -> Dict[str, Any]:
    if not PUBLIC_HOST:
        raise HTTPException(status_code=500, detail="PUBLIC_HOST not set")
    if not HMAC_SECRET:
        raise HTTPException(status_code=500, detail="WEBHOOK_HMAC_SECRET/OPS_SIGN_SECRET not set")

    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    sig = _sign_hex(HMAC_SECRET, raw)
    url = f"{PUBLIC_HOST.rstrip('/')}/ops/approve/signed"
    async with httpx.AsyncClient(timeout=15.0) as cli:
        r = await cli.post(url, content=raw,
                           headers={"Content-Type": "application/json", "X-Signature": sig})
        try:
            j = r.json()
        except Exception:
            j = {"ok": False, "status": r.status_code, "text": r.text}
        if r.status_code >= 400 or not j.get("ok"):
            raise HTTPException(status_code=502, detail=f"approve/signed failed: {j}")
        return j

async def _send_telegram_text(text: str) -> Optional[Dict[str, Any]]:
    if not ADMIN_CHAT_ID or not PUBLIC_HOST:
        return None
    ping_url = f"{PUBLIC_HOST.rstrip('/')}/telegram/ping"
    params = {"chat_id": ADMIN_CHAT_ID, "text": text}
    async with httpx.AsyncClient(timeout=10.0) as cli:
        try:
            rr = await cli.get(ping_url, params=params)
            return rr.json()
        except Exception:
            return None

# -------------------- API --------------------

@router.post("/ops/ticket", summary="Create approval ticket and send Telegram inline buttons (LIVE)")
async def create_ticket(
    payload: Dict[str, Any] = Body(..., description="symbol, side, qty, lev, budget, optional: note, position_side"),
):
    symbol = (payload.get("symbol") or "").upper().strip()
    side   = (payload.get("side") or "").upper().strip()
    qty    = float(payload.get("qty") or 0)
    lev    = int(payload.get("lev") or 0)
    budget = float(payload.get("budget") or 0)
    note   = payload.get("note") or ""
    position_side = (payload.get("position_side") or "BOTH").upper()

    if not (symbol and side and qty > 0 and lev > 0 and budget > 0):
        raise HTTPException(status_code=422, detail="Missing/invalid fields (symbol/side/qty/lev/budget)")

    tid = f"T_{secrets.token_hex(4)}"
    req_body = {
        "action": "approve",
        "ticket_id": tid,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": None,
        "lev": lev,
        "position_side": position_side,
        "budget": budget,
    }
    record = {
        "ts": time.time(),
        "req": req_body,
        "note": note,
    }

    r = await _redis()
    await r.setex(KEY_TICKET(tid), TICKET_TTL_SEC, json.dumps(record, separators=(",", ":")))

    approve_url = f"{PUBLIC_HOST.rstrip('/')}/ops/approve-link?id={tid}"
    reject_url  = f"{PUBLIC_HOST.rstrip('/')}/ops/reject?id={tid}"

    pretty = (
        "⚠️ Approval Needed\n"
        f"• Ticket: {tid}\n"
        f"• {symbol} {side} qty={qty} lev={lev} budget={budget}\n"
        f"• Note: {note}\n— — —\nבחר:"
    )
    tg = await _send_telegram_text(pretty + f"\n✅ {approve_url}\n❌ {reject_url}")

    return {
        "ok": True,
        "ticket_id": tid,
        "approve_url": approve_url,
        "reject_url": reject_url,
        "telegram": tg,
    }

@router.get("/ops/approve-link", summary="Approve ticket via Redis -> calls /ops/approve/signed")
async def approve_link(id: str = Query(..., description="ticket_id")):
    r = await _redis()
    raw = await r.get(KEY_TICKET(id))
    if not raw:
        raise HTTPException(status_code=404, detail="Invalid or expired approval id")
    try:
        rec = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupted ticket payload")

    if _expired(rec.get("ts", 0)):
        await r.delete(KEY_TICKET(id))
        raise HTTPException(status_code=410, detail="Approval link expired")

    req = rec.get("req") or {}
    await _execute_via_signed_endpoint(req)

    try:
        await r.delete(KEY_TICKET(id))
    except Exception:
        pass
    return _html("✅ Approved! Order executed on Binance Futures.")

@router.get("/ops/reject", summary="Reject ticket (delete from Redis)")
async def reject(id: str = Query(..., description="ticket_id")):
    try:
        r = await _redis()
        await r.delete(KEY_TICKET(id))
    except Exception:
        pass
    return _html("❌ Rejected. Order cancelled.")












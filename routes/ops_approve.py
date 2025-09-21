# routes/ops_approve.py
from __future__ import annotations
import os, json, time, hmac, hashlib, httpx, secrets
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Body, Query, Request
from fastapi.responses import HTMLResponse

# Redis (async)
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

router = APIRouter(tags=["ops-approval"])

# -------------------- CFG --------------------
NS                  = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL           = os.getenv("REDIS_URL", "")
PUBLIC_HOST         = (os.getenv("PUBLIC_HOST") or os.getenv("WEBHOOK_HOST") or "").strip()
HMAC_SECRET         = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()
ADMIN_CHAT_ID       = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID")
BOT_TOKEN           = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
API_BEARER_TOKEN    = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()
TICKET_TTL_SEC      = int(os.getenv("OPS_TICKET_TTL_SEC", "1800"))  # 30 דקות

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

async def _send_telegram_text_direct(
    text: str,
    *,
    approve_url: Optional[str] = None,
    reject_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    שליחה ישירה ל-Telegram sendMessage. מחזירה את כל JSON התשובה.
    """
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not set")
    if not ADMIN_CHAT_ID:
        raise HTTPException(status_code=500, detail="TELEGRAM_CHAT_ID/ADMIN_CHAT_ID not set")

    payload: Dict[str, Any] = {
        "chat_id": int(ADMIN_CHAT_ID) if str(ADMIN_CHAT_ID).isdigit() else ADMIN_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if approve_url or reject_url:
        payload["reply_markup"] = {
            "inline_keyboard": [[
                {"text": "✅ Approve", "url": approve_url or PUBLIC_HOST or "https://example.com"},
                {"text": "❌ Reject",  "url": reject_url  or PUBLIC_HOST or "https://example.com"},
            ]]
        }

    async with httpx.AsyncClient(timeout=12.0) as cli:
        res = await cli.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)
        try:
            data = res.json()
        except Exception:
            data = {"ok": False, "status": res.status_code, "text": res.text}
        if res.status_code >= 400 or not data.get("ok"):
            raise HTTPException(status_code=502, detail={"telegram_error": data, "status": res.status_code})
        return data

# -------- Internal executor --------
async def _execute_internal(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    קורא ל-/trade/execute בתוך אותה אפליקציה עם Bearer.
    input (backward compat from ticket): symbol, side, qty, lev, budget, position_side, note?
    mapped → TradeReq: symbol, side, quantity, leverage, budget_usd, position_side, note
    """
    if not API_BEARER_TOKEN:
        raise HTTPException(status_code=500, detail="API_BEARER_TOKEN not set")

    # --- mapping & validation ---
    symbol = (body.get("symbol") or "").upper().strip()
    side   = (body.get("side") or "").upper().strip()
    quantity = float(body.get("quantity") or body.get("qty") or 0)
    leverage = int(body.get("leverage") or body.get("lev") or 0)
    budget_usd = float(body.get("budget_usd") or body.get("budget") or 0.0)
    position_side = (body.get("position_side") or "BOTH").upper()
    note = body.get("note") or "approved ticket"

    if not (symbol and side and quantity > 0 and leverage > 0 and budget_usd > 0):
        raise HTTPException(status_code=422, detail={
            "invalid_execute_payload": {
                "symbol": symbol, "side": side, "quantity": quantity,
                "leverage": leverage, "budget_usd": budget_usd, "position_side": position_side
            }
        })

    payload = {
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "leverage": leverage,
        "budget_usd": budget_usd,
        "position_side": position_side,
        "note": note,
    }

    headers = {"Authorization": f"Bearer {API_BEARER_TOKEN}", "Content-Type": "application/json"}
    url = f"{(PUBLIC_HOST or '').rstrip('/')}/trade/execute" if (PUBLIC_HOST or "").strip() else "/trade/execute"

    async with httpx.AsyncClient(timeout=20.0) as cli:
        r = await cli.post(url, json=payload, headers=headers)
        try:
            j = r.json()
        except Exception:
            j = {"ok": False, "status": r.status_code, "text": r.text}
        if r.status_code >= 400 or not j.get("ok"):
            raise HTTPException(status_code=502, detail={"execute_error": j, "status": r.status_code})
        return j

async def _execute_via_signed_endpoint(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    תאימות לאחור (אם עדיין בשימוש): קריאה ל-/ops/approve/signed עם HMAC.
    """
    if not PUBLIC_HOST:
        raise HTTPException(status_code=500, detail="PUBLIC_HOST not set")
    if not HMAC_SECRET:
        raise HTTPException(status_code=500, detail="WEBHOOK_HMAC_SECRET/OPS_SIGN_SECRET not set")

    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    sig = _sign_hex(HMAC_SECRET, raw)
    url = f"{PUBLIC_HOST.rstrip('/')}/ops/approve/signed"
    async with httpx.AsyncClient(timeout=15.0) as cli:
        r = await cli.post(url, content=raw, headers={"Content-Type": "application/json", "X-Signature": sig})
        try:
            j = r.json()
        except Exception:
            j = {"ok": False, "status": r.status_code, "text": r.text}
        if r.status_code >= 400 or not j.get("ok"):
            raise HTTPException(status_code=502, detail=f"approve/signed failed: {j}")
        return j

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
        "note": note,
    }
    record = {"ts": time.time(), "req": req_body, "note": note}

    r = await _redis()
    await r.setex(KEY_TICKET(tid), TICKET_TTL_SEC, json.dumps(record, separators=(",", ":")))

    approve_url = f"{PUBLIC_HOST.rstrip('/')}/ops/approve-link?id={tid}"
    reject_url  = f"{PUBLIC_HOST.rstrip('/')}/ops/reject?id={tid}"

    pretty = (
        "⚠️ <b>Approval Needed</b>\n"
        f"• Ticket: <code>{tid}</code>\n"
        f"• {symbol} {side} qty={qty} lev={lev} budget={budget}\n"
        f"• Note: {note}\n— — —\nבחר:"
    )

    tg_resp = await _send_telegram_text_direct(pretty, approve_url=approve_url, reject_url=reject_url)

    return {"ok": True, "ticket_id": tid, "approve_url": approve_url, "reject_url": reject_url, "telegram_result": tg_resp}

@router.get("/ops/ticket/{ticket_id}", summary="Debug: fetch ticket from Redis (requires Bearer)")
async def get_ticket(ticket_id: str):
    r = await _redis()
    raw = await r.get(KEY_TICKET(ticket_id))
    if not raw:
        raise HTTPException(status_code=404, detail="Ticket not found")
    try:
        return {"ok": True, "ticket": json.loads(raw)}
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupted ticket payload")

@router.get("/ops/approve-link", summary="Approve ticket via Redis -> execute trade")
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

    # ביצוע בפועל (פנימי) – כולל מיפוי לשמות החדשים
    exec_res = await _execute_internal(req)

    # הודעת טלגרם על אישור
    try:
        sym = req.get("symbol", "")
        side = req.get("side", "")
        qty  = req.get("qty", "")
        await _send_telegram_text_direct(
            f"✅ <b>Approved</b>\n"
            f"• Ticket: <code>{id}</code>\n"
            f"• {sym} {side} qty={qty}\n"
            f"— — —\nExecuted internally: <code>{json.dumps(exec_res, ensure_ascii=False)}</code>"
        )
    except Exception:
        pass

    # ניקוי הטיקט
    try:
        await r.delete(KEY_TICKET(id))
    except Exception:
        pass

    return _html("✅ Approved! Order executed (stateless link).")

# -------- Signed execution endpoint --------
@router.post("/ops/approve/signed", summary="Internal signed approve endpoint (executes trade)")
async def approve_signed(request: Request):
    """
    Verifies HMAC (X-Signature) over raw JSON body and EXECUTES trade internally.
    """
    if not HMAC_SECRET:
        raise HTTPException(status_code=500, detail="HMAC secret not set")

    raw = await request.body()
    got = request.headers.get("X-Signature", "") or ""
    want = _sign_hex(HMAC_SECRET, raw)
    if not hmac.compare_digest(got, want):
        raise HTTPException(status_code=401, detail="Bad signature")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # ביצוע בפועל (פנימי)
    try:
        exec_res = await _execute_internal(payload)
        return {"ok": True, "ticket_id": payload.get("ticket_id"), "executed": True, "internal_execute": exec_res}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})

@router.get("/ops/reject", summary="Reject ticket (delete from Redis)")
async def reject(id: str = Query(..., description="ticket_id")):
    try:
        r = await _redis()
        await r.delete(KEY_TICKET(id))
    except Exception:
        pass

    try:
        await _send_telegram_text_direct(
            f"❌ <b>Rejected</b>\n"
            f"• Ticket: <code>{id}</code>\n"
            f"— — —\nNo action was taken."
        )
    except Exception:
        pass

    return _html("❌ Rejected. Order cancelled.")











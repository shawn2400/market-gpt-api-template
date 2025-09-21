# routes/ops_approve.py
from __future__ import annotations
import os, json, time, hmac, hashlib, httpx, secrets, asyncio
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
NS                   = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL            = os.getenv("REDIS_URL", "")
PUBLIC_HOST          = (os.getenv("PUBLIC_HOST") or os.getenv("WEBHOOK_HOST") or "").strip()
HMAC_SECRET          = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()
ADMIN_CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID")
BOT_TOKEN            = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
API_BEARER           = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()
TICKET_TTL_SEC       = int(os.getenv("OPS_TICKET_TTL_SEC", "1800"))  # 30 דקות
PUBSUB_CHANNEL       = os.getenv("APPROVAL_PUBSUB_CHANNEL", "ops:ticket:events")
AUTO_OPEN_ON_APPROVE = os.getenv("AUTO_OPEN_ON_APPROVE", "1") not in ("0", "false", "False")
EXECUTE_TRADES       = os.getenv("EXECUTE_TRADES", "1") not in ("0", "false", "False")

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
    """
    קורא ל- /ops/approve/signed על ה-PUBLIC_HOST עם חתימת HMAC בכותרת X-Signature.
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

# ---------- Telegram (DIRECT ONLY) ----------
async def _send_telegram_text_direct(
    text: str,
    *,
    approve_url: Optional[str] = None,
    reject_url: Optional[str] = None,
) -> Dict[str, Any]:
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
        data = res.json()
        if res.status_code >= 400 or not data.get("ok"):
            raise HTTPException(status_code=502, detail={"telegram_error": data, "status": res.status_code})
        return data

# ---------- Local executor helpers ----------
async def _try_call_internal_executor(req: Dict[str, Any]) -> Dict[str, Any]:
    """
    ניסיון אקזקיושן דרך ראוטים פנימיים אם קיימים:
      1) /trade/market
      2) /trade/open
    מחזיר dict עם מפתחות: ok, tried, status, response (אם יש).
    """
    if not PUBLIC_HOST or not API_BEARER:
        return {"ok": False, "tried": [], "error": "missing PUBLIC_HOST/API_BEARER"}

    tried = []
    headers = {"Authorization": f"Bearer {API_BEARER}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=20.0) as cli:
        # 1) /trade/market
        url1 = f"{PUBLIC_HOST.rstrip('/')}/trade/market"
        tried.append(url1)
        try:
            r1 = await cli.post(url1, json={
                "symbol": req.get("symbol"),
                "side": req.get("side"),
                "qty": req.get("qty"),
                "lev": req.get("lev"),
                "position_side": req.get("position_side", "BOTH"),
                "budget": req.get("budget"),
                "reduce_only": False,
                "note": f"approved:{req.get('ticket_id')}",
            }, headers=headers)
            j1 = r1.json() if r1.headers.get("content-type","").startswith("application/json") else {"text": r1.text}
            if r1.status_code < 400 and (j1.get("ok") is True or "orderId" in json.dumps(j1)):
                return {"ok": True, "tried": tried, "status": r1.status_code, "response": j1}
        except Exception as e:
            pass

        # 2) /trade/open
        url2 = f"{PUBLIC_HOST.rstrip('/')}/trade/open"
        tried.append(url2)
        try:
            r2 = await cli.post(url2, json=req, headers=headers)
            j2 = r2.json() if r2.headers.get("content-type","").startswith("application/json") else {"text": r2.text}
            if r2.status_code < 400 and (j2.get("ok") is True or "orderId" in json.dumps(j2)):
                return {"ok": True, "tried": tried, "status": r2.status_code, "response": j2}
        except Exception as e:
            pass

    return {"ok": False, "tried": tried, "error": "no internal executor routes responded with ok"}

async def _publish_redis_event(kind: str, data: Dict[str, Any]) -> Optional[int]:
    """
    פרסום לאפיק Pub/Sub כדי שה־Manager יבצע.
    """
    try:
        r = await _redis()
        msg = {"kind": kind, "ts": time.time(), **data}
        n = await r.publish(PUBSUB_CHANNEL, json.dumps(msg, separators=(",", ":")))
        return n
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

    return {
        "ok": True,
        "ticket_id": tid,
        "approve_url": approve_url,
        "reject_url": reject_url,
        "telegram_result": tg_resp,
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
        sym = req.get("symbol", "")
        side = req.get("side", "")
        qty  = req.get("qty", "")
        await _send_telegram_text_direct(
            f"✅ <b>Approved</b>\n"
            f"• Ticket: <code>{id}</code>\n"
            f"• {sym} {side} qty={qty}\n"
            f"— — —\nExecuted via signed endpoint."
        )
    except Exception:
        pass

    try:
        await r.delete(KEY_TICKET(id))
    except Exception:
        pass

    return _html("✅ Approved! Order executed (or queued) via executor/manager.")

# -------- Signed execution endpoint --------
@router.post("/ops/approve/signed", summary="Internal signed approve endpoint")
async def approve_signed(request: Request):
    """
    Verifies HMAC (X-Signature) over raw JSON body.
    Then attempts to EXECUTE:
      1) Call internal /trade/market (or /trade/open) with Bearer.
      2) If missing -> publish to Redis Pub/Sub for manager.
    Returns JSON with detailed path taken.
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

    ticket_id = payload.get("ticket_id")
    # Ensure required fields exist
    for k in ("symbol", "side", "qty", "lev", "position_side", "budget"):
        if k not in payload:
            raise HTTPException(status_code=422, detail=f"Missing field: {k}")

    exec_result: Dict[str, Any] = {"path": None}

    if EXECUTE_TRADES and AUTO_OPEN_ON_APPROVE:
        # Try internal executor routes first
        exec_try = await _try_call_internal_executor(payload)
        exec_result["internal_executor"] = exec_try
        if exec_try.get("ok"):
            exec_result["path"] = "internal_executor"
        else:
            # publish to manager via redis
            pub = await _publish_redis_event("approved", {"ticket_id": ticket_id, "req": payload})
            exec_result["redis_pubsub"] = {"published_to": PUBSUB_CHANNEL, "receivers": pub}
            exec_result["path"] = "redis_pubsub"
    else:
        # Manager-only path
        pub = await _publish_redis_event("approved", {"ticket_id": ticket_id, "req": payload})
        exec_result["redis_pubsub"] = {"published_to": PUBSUB_CHANNEL, "receivers": pub}
        exec_result["path"] = "redis_pubsub"

    # Telegram notify (best effort)
    try:
        p = payload
        await _send_telegram_text_direct(
            f"📤 <b>Dispatch</b>\n"
            f"• Ticket: <code>{ticket_id}</code>\n"
            f"• {p.get('symbol')} {p.get('side')} qty={p.get('qty')} lev={p.get('lev')}\n"
            f"• Path: <code>{exec_result.get('path')}</code>"
        )
    except Exception:
        pass

    return {"ok": True, "ticket_id": ticket_id, "executed": True, "exec_result": exec_result}








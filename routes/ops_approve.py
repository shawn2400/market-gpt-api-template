# routes/ops_approve.py
from __future__ import annotations
from typing import Optional, Dict, Any
import os, time, hmac, hashlib, json, logging

import httpx
from fastapi import APIRouter, Query, Request, Header, HTTPException
from fastapi.responses import JSONResponse

# Redis (async)
try:
    import redis.asyncio as aioredis
except Exception:
    aioredis = None

router = APIRouter(prefix="/ops", tags=["Ops"])
log = logging.getLogger("ops.approval")

# ---------- Trading flow (unchanged) ----------
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
            ctype = (r.headers.get("content-type", "") or "").split(";")[0].strip().lower()
            data = r.json() if ctype == "application/json" else {"text": r.text}
            return {"ok": r.status_code < 400, "status": r.status_code, "response": data}
    except Exception as e:
        return {"ok": False, "error": f"http_error: {e}"}

# ---------- Approval (tickets) ----------
PUBSUB_CHANNEL  = os.getenv("APPROVAL_PUBSUB_CHANNEL", "ops:ticket:events")
REDIS_URL       = os.getenv("REDIS_URL", "")
NS              = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
WEBHOOK_SECRET  = (os.getenv("WEBHOOK_HMAC_SECRET", "")).encode("utf-8") if os.getenv("WEBHOOK_HMAC_SECRET") else None
ALLOWLIST_RAW   = os.getenv("APPROVER_ALLOWLIST", "")
ALLOWLIST       = {x.strip() for x in ALLOWLIST_RAW.split(",") if x.strip()}
REQUIRE_UNIQUE  = os.getenv("REQUIRE_UNIQUE_APPROVERS", "1").lower() in ("1","true","yes","on")
REQUIRE_ID      = os.getenv("REQUIRE_APPROVER_ID", "1").lower() in ("1","true","yes","on")

KEY_TICKET = lambda tid: f"{NS}:ticket:{tid}"
KEY_DEC   = lambda tid: f"{NS}:ticket:{tid}:decisions"  # Redis Set of approver ids

async def _redis():
    if not aioredis:
        raise RuntimeError("redis.asyncio not available")
    if not REDIS_URL:
        raise RuntimeError("REDIS_URL not set")
    return await aioredis.from_url(REDIS_URL, decode_responses=True)

def _hmac_sig(ticket_id: str, action: str, expires: str) -> str:
    base = f"{ticket_id}|{action}|{expires}".encode("utf-8")
    return hmac.new(WEBHOOK_SECRET, base, hashlib.sha256).hexdigest() if WEBHOOK_SECRET else ""

def _assert(cond: bool, msg: str):
    if not cond:
        raise HTTPException(status_code=400, detail=msg)

# ---------- Unified endpoint ----------
@router.get("/approve", summary="Approve trade OR approve/reject ticket (auto-detect)")
async def ops_approve(
    # --- ticket params (optional) ---
    ticket_id: Optional[str] = Query(None, description="When present, approval flow is used"),
    action: Optional[str] = Query(None, regex="^(approve|reject)$"),
    expires: Optional[int] = Query(None, ge=0),
    sig: Optional[str] = Query(None),
    by: Optional[str] = Query(None, description="Approver id (Telegram chat id)"),
    # --- trading params (backward-compatible) ---
    symbol: Optional[str] = Query(None, description="e.g. BTCUSDT"),
    side: Optional[str] = Query(None, description="BUY/SELL for spot or LONG/SHORT for futures"),
    tf: Optional[str] = Query("15m", description="timeframe"),
    score: Optional[float] = Query(None),
    src: Optional[str] = Query("scan"),
    chat_id: Optional[str] = Query(None),
    market: str = Query("futures", description="futures|spot"),
    account_id: str = Query("main"),
    budget: float = Query(10.0),
    leverage: Optional[int] = Query(10),
    grids: int = Query(3),
    dry_run: Optional[bool] = Query(True),
):
    """
    אם נשלחו פרמטרי טיקט → אישור/דחייה חתומים ו-Pub/Sub.
    אחרת, אם נשלחו פרמטרי טרייד (symbol/side) → טריגר /grid/trade (כמו שהיה).
    """
    # ---- branch: ticket-approval ----
    if ticket_id or action or expires or sig:
        _assert(WEBHOOK_SECRET is not None, "HMAC secret not configured")
        _assert(ticket_id is not None, "ticket_id required")
        _assert(action in ("approve", "reject"), "action must be approve|reject")
        _assert(expires is not None, "expires required")
        _assert(sig is not None, "sig required")
        _assert(int(time.time()) <= int(expires), "Link expired")
        if REQUIRE_ID:
            _assert(by is not None, "Approver id required")
        if by and ALLOWLIST:
            _assert(by in ALLOWLIST, "Approver not allowed")

        expected = _hmac_sig(ticket_id, action, str(expires))
        _assert(hmac.compare_digest((sig or "").strip().lower(), expected), "Invalid signature")

        r = await _redis()

        # block duplicate approver decisions if required
        if REQUIRE_UNIQUE and by:
            added = await r.sadd(KEY_DEC(ticket_id), by)
            _assert(added == 1, "Duplicate approver for this ticket")

        # ensure ticket key exists (supervisor setex JSON)
        exists = await r.exists(KEY_TICKET(ticket_id))
        _assert(exists == 1, "Unknown or expired ticket")

        event = {
            "ticket_id": ticket_id,
            "action": action,
            "by": by or "unknown",
            "ts": int(time.time()),
            "source": "ops-approval-web",
        }
        await r.publish(PUBSUB_CHANNEL, json.dumps(event))
        log.info("ticket_decision", extra=event)

        return JSONResponse({"ok": True, "mode": "ticket", **event})

    # ---- branch: trading-approval (back-compat) ----
    _assert(symbol is not None and side is not None, "symbol & side required")

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
        "mode": "trade",
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

# ---------- Signed body (trade) ----------
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
    x_signature: str = Header(default="", alias="X-Signature"),
):
    """
    הגוף נחתם מול OPS_SIGN_SECRET (או WEBHOOK_HMAC_SECRET).
    JSON דוגמה:
    {"action":"approve","ticket_id":"T1","symbol":"BTCUSDT","side":"BUY","qty":0.001,"lev":10,"budget":null}
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

    if not symbol or side not in {"BUY", "SELL", "LONG", "SHORT"}:
        return JSONResponse(status_code=400, content={"detail": "invalid symbol/side"})

    if budget is None and qty is not None:
        try:
            budget = float(os.getenv("MIN_NOTIONAL_USDT", "5"))
        except Exception:
            budget = 5.0

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









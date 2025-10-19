# routes/ops_approval.py
from __future__ import annotations

import os
import json
import time
import hmac
import hashlib
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

# Redis (async)
try:
    import redis.asyncio as aioredis
except Exception:
    aioredis = None  # type: ignore

router = APIRouter(tags=["ops-approval"])

# ===== ENV =====
NS: str = (os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web")
REDIS_URL: str = os.getenv("REDIS_URL", "").strip()
PUBLIC_HOST: str = (os.getenv("PUBLIC_HOST") or os.getenv("WEBHOOK_HOST") or "").strip().rstrip("/")
HMAC_SECRET: str = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()

KEY_TICKET = lambda tid: f"{NS}:ticket:{tid}"

# ===== HTML helper =====
def _html(msg: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:560px;margin:3rem auto;line-height:1.5'>"
        f"<h2 style='margin:0'>{msg}</h2>"
        "<p style='color:#666;margin:.5rem 0 0'>אפשר לסגור את החלון ולחזור לטלגרם.</p>"
        "</body>"
    )

# ===== Redis helper (cached client) =====
_redis_client: Optional["aioredis.Redis"] = None  # type: ignore[name-defined]

async def _redis():
    """Return a cached Redis asyncio client or raise 500 if unavailable."""
    global _redis_client
    if not aioredis:
        raise HTTPException(status_code=500, detail="redis.asyncio not available")
    if not REDIS_URL:
        raise HTTPException(status_code=500, detail="REDIS_URL not set")
    if _redis_client is None:
        # IMPORTANT: from_url is not awaitable
        _redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)  # type: ignore[assignment]
    return _redis_client

# ===== Ticket helpers =====
async def _load_ticket(ticket_id: str) -> Dict[str, Any]:
    """Load the ticket JSON from Redis; support both raw req or {'ts':..., 'req': {...}}."""
    r = await _redis()
    raw = await r.get(KEY_TICKET(ticket_id))
    if not raw:
        raise HTTPException(status_code=404, detail="Invalid or expired approval id")
    try:
        data = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupted ticket payload")

    # If main.py stored {"ts":..., "req": {...}} – unwrap it
    if isinstance(data, dict) and ("req" in data or "ts" in data):
        ts = data.get("ts")
        req = data.get("req") or {}
        return {"ts": ts, "req": req}
    # Fallback: assume data itself is the request body
    return {"ts": None, "req": data}

def _expired(ts: Optional[float], ttl_sec: int = 60 * 30) -> bool:
    """Return True if timestamp is older than ttl_sec (default 30m)."""
    try:
        if ts is None:
            return False
        return (time.time() - float(ts)) > ttl_sec
    except Exception:
        return True

# ===== Signing (must match main.py) =====
def _sign_hex(secret: str, payload: bytes) -> str:
    """Sign raw bytes with HMAC-SHA256. If secret looks like hex(64) -> decode; else utf-8."""
    try:
        key = bytes.fromhex(secret) if len(secret) == 64 else secret.encode("utf-8")
    except ValueError:
        key = secret.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

async def _execute_via_signed_endpoint(ticket_id: str) -> Dict[str, Any]:
    """
    Call the signed approve endpoint in main.py:
    POST /ops/approve/signed  (Form fields: ticket_id, exp, sig)
    where sig = HMAC(secret, f"/ops/approve/signed|{ticket_id}|{exp}|{NS}")
    """
    if not PUBLIC_HOST:
        raise HTTPException(status_code=500, detail="PUBLIC_HOST not set")
    if not HMAC_SECRET:
        raise HTTPException(status_code=500, detail="WEBHOOK_HMAC_SECRET/OPS_SIGN_SECRET not set")

    path = "/ops/approve/signed"
    exp = str(int(time.time()) + 600)  # 10 minutes validity
    to_sign = f"{path}|{ticket_id}|{exp}|{NS}".encode("utf-8")
    sig = _sign_hex(HMAC_SECRET, to_sign)

    url = f"{PUBLIC_HOST}{path}"
    async with httpx.AsyncClient(timeout=15.0) as cli:
        r = await cli.post(
            url,
            data={"ticket_id": ticket_id, "exp": exp, "sig": sig},  # form-encoded
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        # main.py returns HTMLResponse on success and JSON on errors (via exception handler)
        # Try parse JSON; if fails, assume HTML ok (status<400)
        if r.status_code >= 400:
            # Try to expose the JSON error payload if present
            try:
                j = r.json()
            except Exception:
                j = {"status": r.status_code, "text": r.text[:300]}
            raise HTTPException(status_code=502, detail=f"approve/signed failed: {j}")
        try:
            return r.json()  # might be {} if HTML returned; that's ok
        except Exception:
            return {"ok": True, "html": True}

# ===== Endpoints =====
@router.get("/ops/approve")
async def approve(
    id: Optional[str] = Query(default=None, description="ticket_id (alias)"),
    ticket_id: Optional[str] = Query(default=None, description="ticket_id"),
):
    tid = ticket_id or id
    if not tid:
        raise HTTPException(status_code=422, detail="ticket_id is required")

    rec = await _load_ticket(tid)
    ts = rec.get("ts")
    if _expired(ts, ttl_sec=60 * 30):
        # Delete silently on expiry
        try:
            r = await _redis()
            await r.delete(KEY_TICKET(tid))
        except Exception:
            pass
        raise HTTPException(status_code=410, detail="Approval link expired")

    # Execute real action through signed endpoint (main.py)
    await _execute_via_signed_endpoint(tid)

    # Delete after execution
    try:
        r = await _redis()
        await r.delete(KEY_TICKET(tid))
    except Exception:
        pass
    return _html("✅ Approved! Order executed on Binance Futures.")

@router.get("/ops/reject")
async def reject(
    id: Optional[str] = Query(default=None, description="ticket_id (alias)"),
    ticket_id: Optional[str] = Query(default=None, description="ticket_id"),
):
    tid = ticket_id or id
    if not tid:
        raise HTTPException(status_code=422, detail="ticket_id is required")

    # Fast delete from Redis (best-effort)
    try:
        r = await _redis()
        await r.delete(KEY_TICKET(tid))
    except Exception:
        pass
    return _html("❌ Rejected. Order cancelled.")




# routes/ops_approval.py
from __future__ import annotations
import os, json, time, hmac, hashlib, httpx
from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

# Redis (async)
try:
    import redis.asyncio as aioredis
except Exception:
    aioredis = None  # type: ignore

router = APIRouter(tags=["ops-approval"])

NS          = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL   = os.getenv("REDIS_URL", "")
KEY_TICKET  = lambda tid: f"{NS}:ticket:{tid}"

PUBLIC_HOST = (os.getenv("PUBLIC_HOST") or os.getenv("WEBHOOK_HOST") or "").strip()
HMAC_SECRET = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()

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
    return await aioredis.from_url(REDIS_URL, decode_responses=True)

async def _load_ticket(ticket_id: str) -> Dict[str, Any]:
    r = await _redis()
    raw = await r.get(KEY_TICKET(ticket_id))
    if not raw:
        raise HTTPException(status_code=404, detail="Invalid or expired approval id")
    try:
        data = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupted ticket payload")
    return data

def _expired(ts: float, ttl_sec: int = 60 * 15) -> bool:
    try:
        return (time.time() - float(ts)) > ttl_sec
    except Exception:
        return True

def _sign_hex(secret_hex: str, payload: bytes) -> str:
    # secret is hex-string (64 chars) — same כמו ב-/_debug/hmac
    key = bytes.fromhex(secret_hex) if len(secret_hex) == 64 else secret_hex.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

async def _execute_via_signed_endpoint(body: Dict[str, Any]) -> Dict[str, Any]:
    if not PUBLIC_HOST:
        raise HTTPException(status_code=500, detail="PUBLIC_HOST not set")
    if not HMAC_SECRET:
        raise HTTPException(status_code=500, detail="WEBHOOK_HMAC_SECRET/OPS_SIGN_SECRET not set")

    raw = json.dumps(body, separators=(",",":")).encode("utf-8")
    sig = _sign_hex(HMAC_SECRET, raw)
    url = f"{PUBLIC_HOST.rstrip('/')}/ops/approve/signed"
    async with httpx.AsyncClient(timeout=15.0) as cli:
        r = await cli.post(url, content=raw, headers={"Content-Type":"application/json", "X-Signature": sig})
        try:
            j = r.json()
        except Exception:
            j = {"ok": False, "status": r.status_code, "text": r.text}
        if r.status_code >= 400 or not j.get("ok"):
            raise HTTPException(status_code=502, detail=f"approve/signed failed: {j}")
        return j

@router.get("/ops/approve")
async def approve(id: str = Query(..., description="ticket_id")):
    rec = await _load_ticket(id)
    if _expired(rec.get("ts", 0), ttl_sec=60*30):
        # מחיקה שקטה במקרה תוקף פג
        try:
            r = await _redis(); await r.delete(KEY_TICKET(id))
        except Exception: pass
        raise HTTPException(status_code=410, detail="Approval link expired")

    req = rec.get("req") or {}
    # ביצוע אמיתי דרך ה-endpoint החתום שכבר תקין אצלך
    await _execute_via_signed_endpoint(req)

    # מחיקת הטיקט אחרי ביצוע
    try:
        r = await _redis(); await r.delete(KEY_TICKET(id))
    except Exception: pass
    return _html("✅ Approved! Order executed on Binance Futures.")

@router.get("/ops/reject")
async def reject(id: str = Query(..., description="ticket_id")):
    # מחיקה מהירה מה-Redis
    try:
        r = await _redis(); await r.delete(KEY_TICKET(id))
    except Exception:
        pass
    return _html("❌ Rejected. Order cancelled.")





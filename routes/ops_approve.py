from __future__ import annotations
from typing import Optional, Dict, Any
import os, time, hmac, hashlib, json, logging
import httpx
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse

try:
    import redis.asyncio as aioredis
except Exception:
    aioredis = None

router = APIRouter(prefix="/ops", tags=["Ops"])
log = logging.getLogger("ops.approval")

PUBLIC_HOST    = os.getenv("PUBLIC_HOST", "").rstrip("/")
INTERNAL_TOKEN = os.getenv("OPS_INTERNAL_TOKEN") or os.getenv("API_TOKEN") or os.getenv("TOKEN")

async def _post_grid_trade(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not PUBLIC_HOST:    return {"ok": False, "error": "PUBLIC_HOST not set"}
    if not INTERNAL_TOKEN: return {"ok": False, "error": "OPS_INTERNAL_TOKEN not set"}
    url = f"{PUBLIC_HOST}/grid/trade"
    headers = {"Authorization": f"Bearer {INTERNAL_TOKEN}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(url, headers=headers, json=payload)
            ctype = (r.headers.get("content-type","") or "").split(";")[0].strip().lower()
            data = r.json() if ctype == "application/json" else {"text": r.text}
            return {"ok": r.status_code < 400, "status": r.status_code, "response": data}
    except Exception as e:
        return {"ok": False, "error": f"http_error: {e}"}

PUBSUB_CHANNEL = os.getenv("APPROVAL_PUBSUB_CHANNEL", "ops:ticket:events")
REDIS_URL      = os.getenv("REDIS_URL", "")
NS             = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
WEBHOOK_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "")
ALLOWLIST      = {x.strip() for x in (os.getenv("APPROVER_ALLOWLIST","")).split(",") if x.strip()}
REQUIRE_UNIQUE = os.getenv("REQUIRE_UNIQUE_APPROVERS", "1").lower() in ("1","true","yes","on")
REQUIRE_ID     = os.getenv("REQUIRE_APPROVER_ID", "1").lower() in ("1","true","yes","on")

KEY_TICKET = lambda tid: f"{NS}:ticket:{tid}"
KEY_DEC    = lambda tid: f"{NS}:ticket:{tid}:decisions"

async def _redis():
    if not aioredis:
        raise RuntimeError("redis.asyncio not available")
    if not REDIS_URL:
        raise RuntimeError("REDIS_URL not set")
    return await aioredis.from_url(REDIS_URL, decode_responses=True)

def _sig_legacy(ticket_id: str, action: str, expires: str) -> str:
    if not WEBHOOK_SECRET: return ""
    base = f"{ticket_id}|{action}|{expires}".encode("utf-8")
    return hmac.new(WEBHOOK_SECRET.encode("utf-8"), base, hashlib.sha256).hexdigest()

def _sig_canonical(qs_params: Dict[str, Optional[str]]) -> str:
    if not WEBHOOK_SECRET: return ""
    allow = {"ticket_id","action","expires","require","version","by"}
    items = {k: v for k, v in qs_params.items() if k in allow and v is not None}
    canon = "&".join(f"{k}={items[k]}" for k in sorted(items))
    return hmac.new(WEBHOOK_SECRET.encode("utf-8"), canon.encode("utf-8"), hashlib.sha256).hexdigest()

def _assert(cond: bool, msg: str):
    if not cond:
        raise HTTPException(status_code=400, detail=msg)

def _bool(x):
    if x is None: return None
    s = str(x).strip().lower()
    if s in ("1","true","yes","on"): return True
    if s in ("0","false","no","off"): return False
    return None

@router.get("/approve", summary="Approve trade OR ticket (auto-detect)")
async def ops_approve(
    ticket_id: Optional[str] = Query(None),
    action:   Optional[str] = Query(None, pattern="^(approve|reject)$"),
    expires:  Optional[int] = Query(None, ge=0),
    sig:      Optional[str] = Query(None),
    by:       Optional[str] = Query(None),
    require:  Optional[int] = Query(None, ge=1, le=2),
    version:  Optional[str] = Query(None),
    symbol:   Optional[str] = Query(None),
    side:     Optional[str] = Query(None),
    tf:       Optional[str] = Query("15m"),
    score:    Optional[float] = Query(None),
    src:      Optional[str] = Query("scan"),
    chat_id:  Optional[str] = Query(None),
    market:   str = Query("futures"),
    account_id: str = Query("main"),
    budget:   float = Query(10.0),
    leverage: Optional[int] = Query(10),
    grids:    int = Query(3),
    dry_run:  Optional[bool] = Query(True),
):
    # ----- ticket branch -----
    if ticket_id or action or expires or sig or require or version:
        _assert(WEBHOOK_SECRET, "HMAC secret not configured")
        _assert(ticket_id is not None, "ticket_id required")
        _assert(action in ("approve","reject"), "action must be approve|reject")
        _assert(expires is not None, "expires required")
        _assert(sig is not None, "sig required")
        _assert(int(time.time()) <= int(expires), "Link expired")
        if REQUIRE_ID: _assert(by is not None, "Approver id required")
        if by and ALLOWLIST: _assert(by in ALLOWLIST, "Approver not allowed")

        qs = {
            "ticket_id": ticket_id,
            "action": action,
            "expires": str(expires),
            "require": str(require) if require is not None else None,
            "version": version,
            "by": by,
        }
        expected_legacy = _sig_legacy(ticket_id, action, str(expires))
        expected_canon  = _sig_canonical(qs)
        provided = (sig or "").strip().lower()
        _assert(provided in (expected_legacy, expected_canon), "Invalid signature")

        r = await _redis()
        if REQUIRE_UNIQUE and by:
            added = await r.sadd(KEY_DEC(ticket_id), by)
            _assert(added == 1, "Duplicate approver for this ticket")

        exists = await r.exists(KEY_TICKET(ticket_id))
        _assert(exists == 1, "Unknown or expired ticket")

        event = {
            "id": ticket_id,
            "status": "approved" if action == "approve" else "rejected",
            "by": by or "unknown",
            "ts": int(time.time()),
        }
        await r.publish(PUBSUB_CHANNEL, json.dumps(event))
        log.info("ticket_decision", extra=event)
        return JSONResponse({"ok": True, "mode": "ticket", **event})

    # ----- trade branch (back-compat) -----
    _assert(symbol is not None and side is not None, "symbol & side required")
    payload: Dict[str, Any] = {
        "symbol": (symbol or "").upper(),
        "side": (side or "").upper(),
        "budget": float(budget),
        "grids": int(grids),
        "dry_run": bool(_bool(dry_run) if dry_run is not None else True),
        "market": (market or "").lower(),
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
    return {"ok": bool(result.get("ok")), "mode": "trade", "action": "approve", "request": payload, "result": result}

@router.get("/reject", summary="Reject trade (echo)")
async def ops_reject(
    symbol: str,
    side: str,
    tf: Optional[str] = "15m",
    score: Optional[float] = None,
    src: Optional[str] = "scan",
    chat_id: Optional[str] = None,
):
    return {
        "ok": True,
        "action": "reject",
        "symbol": symbol.upper(),
        "side": side.upper(),
        "meta": {"source": src, "timeframe": tf, "score": score, "chat_id": chat_id, "ts": int(time.time())},
    }









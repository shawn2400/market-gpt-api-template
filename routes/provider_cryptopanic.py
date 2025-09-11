# routes/provider_cryptopanic.py
from __future__ import annotations
import os
import hmac
import hashlib
import logging
import time
import json
from typing import Optional, Tuple, Dict, Any

import httpx
from fastapi import APIRouter, Request, HTTPException

logger = logging.getLogger("provider.cryptopanic")
router = APIRouter(prefix="/provider/cryptopanic", tags=["provider:cryptopanic"])

# ────────────────────────────────────────────────────────────────────────────────
# Redis (optional) – fallback to in-memory
# ────────────────────────────────────────────────────────────────────────────────
_redis = None
try:
    from redis.asyncio import from_url as redis_from_url  # type: ignore
    _REDIS_URL = os.getenv("REDIS_URL", "").strip()
    if _REDIS_URL:
        _redis = redis_from_url(_REDIS_URL, decode_responses=True)
except Exception as _e:
    logger.info("Redis not available, falling back to in-memory. err=%s", _e)

# In-memory fallback stores
_idem_mem: Dict[str, float] = {}
_rate_mem: Dict[str, Tuple[int, float]] = {}  # key -> (count, window_expiry_ts)

def _now() -> int:
    return int(time.time())

# ────────────────────────────────────────────────────────────────────────────────
# Helpers: allowlist / client IP
# ────────────────────────────────────────────────────────────────────────────────
def _parse_allowlist(raw: str | None) -> set[str]:
    if not raw:
        return set()
    s = raw.strip().strip('"').strip("'")
    parts = []
    for sep in [",", "\n", " "]:
        if sep in s:
            parts = [p for p in (x.strip() for x in s.split(sep)) if p]
            # keep splitting cascade to catch weird mixes
            s = ",".join(parts)
    if not parts:
        parts = [s] if s else []
    return set(parts)

def _real_ip(request: Request) -> str:
    # Behind proxies, Render וכו' – נעדיף X-Forwarded-For ראשון אם קיים
    xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if xff:
        # יכול להכיל "client, proxy1, proxy2"
        return xff.split(",")[0].strip()
    # אחרת socket
    try:
        return request.client.host  # type: ignore
    except Exception:
        return "0.0.0.0"

def _ip_allowed(request: Request) -> bool:
    allowlist = _parse_allowlist(os.getenv("CP_IP_ALLOWLIST"))
    if not allowlist:
        # אם לא הוגדר – לא מחסום IP
        return True
    ip = _real_ip(request)
    return ip in allowlist

# ────────────────────────────────────────────────────────────────────────────────
# Helpers: HMAC Signature
# ────────────────────────────────────────────────────────────────────────────────
def _extract_headers(request: Request) -> Tuple[str, str]:
    ts = request.headers.get("X-CP-Timestamp") or request.headers.get("x-cp-timestamp") or ""
    sig = request.headers.get("X-CP-Signature") or request.headers.get("x-cp-signature") or ""
    return ts.strip(), sig.strip()

def _verify_hmac(ts: str, body: bytes) -> None:
    secret = (os.getenv("CP_HMAC_SECRET") or "").strip()
    if not secret:
        raise HTTPException(status_code=401, detail="CP_HMAC_SECRET not configured")

    # Validate timestamp skew
    max_skew = int(os.getenv("CP_MAX_SKEW_SEC", "180") or "180")
    try:
        ts_int = int(ts)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid X-CP-Timestamp")

    if abs(_now() - ts_int) > max_skew:
        raise HTTPException(status_code=401, detail="Timestamp skew too large")

    # Signature format: "sha256=<hex>"
    # We accept with or without the "sha256=" prefix
    provided = (_extract_sig_hex := (lambda s: s.split("=", 1)[-1]))(request_state.sig)  # type: ignore[name-defined]
    raw = f"{ts}.{body.decode('utf-8')}"
    calc = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calc, provided):
        raise HTTPException(status_code=401, detail="Invalid signature")

# ────────────────────────────────────────────────────────────────────────────────
# Helpers: Idempotency
# ────────────────────────────────────────────────────────────────────────────────
async def _already_processed(key: str, ttl: int) -> bool:
    if _redis:
        try:
            # SET key 1 NX EX ttl
            ok = await _redis.set(key, "1", ex=ttl, nx=True)
            return not bool(ok)
        except Exception as e:
            logger.warning("Redis idempotency failed, fallback to memory: %s", e)

    # Fallback – memory
    now = time.time()
    # purge small
    dead = [k for k, exp in _idem_mem.items() if exp < now]
    for k in dead:
        _idem_mem.pop(k, None)
    if key in _idem_mem:
        return True
    _idem_mem[key] = now + ttl
    return False

# ────────────────────────────────────────────────────────────────────────────────
# Helpers: Rate limit
# ────────────────────────────────────────────────────────────────────────────────
async def _rate_limit(key: str, limit: int, window: int) -> None:
    """
    Sliding window via Redis INCR + EXPIRE, else in-memory.
    """
    if limit <= 0:
        return
    if _redis:
        try:
            cnt = await _redis.incr(key)
            if cnt == 1:
                await _redis.expire(key, window)
            if cnt > limit:
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
            return
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Redis rate-limit failed, fallback to memory: %s", e)

    # In-memory fallback
    now = time.time()
    cnt, exp = _rate_mem.get(key, (0, 0.0))
    if exp < now:
        cnt, exp = 0, now + window
    cnt += 1
    _rate_mem[key] = (cnt, exp)
    if cnt > limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

# ────────────────────────────────────────────────────────────────────────────────
# Request-scoped state (to pass sig safely)
# ────────────────────────────────────────────────────────────────────────────────
class _ReqState:
    def __init__(self):
        self.sig = ""

request_state = _ReqState()

# ────────────────────────────────────────────────────────────────────────────────
# Public endpoints
# ────────────────────────────────────────────────────────────────────────────────
@router.get("/ping", summary="CryptoPanic ping")
async def ping():
    return {"ok": True, "src": "cryptopanic", "ts": _now()}

@router.post("/webhook", summary="CryptoPanic Webhook (HMAC + IP allowlist)")
async def webhook(request: Request):
    # 1) IP allowlist
    if not _ip_allowed(request):
        raise HTTPException(status_code=401, detail="IP not allowed")

    # 2) Read raw body
    try:
        body = await request.body()
        # Keep original body for HMAC; also parse JSON for processing
        payload = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # 3) Headers (timestamp + signature)
    ts, sig = _extract_headers(request)
    request_state.sig = sig  # make available to HMAC helper

    # 4) Rate limit (global + per IP)
    rpm = int(os.getenv("CP_RPM", "60") or "60")
    burst = int(os.getenv("CP_BURST", "60") or "60")
    window_rpm = 60
    window_burst = 10
    ip = _real_ip(request)
    await _rate_limit("rl:cp:global:1m", rpm, window_rpm)
    await _rate_limit(f"rl:cp:ip:{ip}:1m", max(1, rpm // 2), window_rpm)
    await _rate_limit("rl:cp:global:burst", burst, window_burst)

    # 5) HMAC
    _verify_hmac(ts, body)

    # 6) Idempotency
    idem_ttl = int(os.getenv("CP_IDEMP_TTL_SEC", "600") or "600")
    idem_key = "idem:cp:" + hashlib.sha256(body).hexdigest()
    if await _already_processed(idem_key, idem_ttl):
        return {"ok": True, "duplicate": True}

    # 7) Optional: forward to sink (if configured)
    sink = (os.getenv("ALERTS_INGEST_URL") or "").strip()
    forwarded = False
    status = None
    if sink:
        try:
            # enrich minimal metadata
            enrich = {
                "source": "cryptopanic",
                "received_ts": _now(),
                "ip": ip,
            }
            merged: Dict[str, Any] = {**payload, **{"_meta": enrich}}
            async with httpx.AsyncClient(timeout=10.0) as cli:
                r = await cli.post(sink, json=merged)
                status = r.status_code
                forwarded = r.status_code < 400
        except Exception as e:
            logger.warning("Forward to sink failed: %s", e)

    return {
        "ok": True,
        "forwarded": forwarded,
        "sink_status": status,
    }


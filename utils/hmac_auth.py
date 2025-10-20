# utils/hmac_auth.py
from __future__ import annotations
import os, hmac, hashlib, time, logging, asyncio
from typing import Optional, Tuple
from fastapi import Request, HTTPException, status

logger = logging.getLogger("algogpt.hmac")

# ===== ENV =====
HMAC_ENABLE               = os.getenv("HMAC_ENABLE", "1").lower() in ("1","true","yes","on")
HMAC_REQUIRE              = os.getenv("HMAC_REQUIRE", "1").lower() in ("1","true","yes","on")
HMAC_HEADER               = os.getenv("HMAC_HEADER", "X-Signature")
HMAC_TS_HEADER            = os.getenv("HMAC_TS_HEADER", "X-Timestamp")
HMAC_NONCE_HEADER         = os.getenv("HMAC_NONCE_HEADER", "X-Nonce")
HMAC_BODY_HASH_HEADER     = os.getenv("HMAC_BODY_HASH_HEADER", "X-Content-SHA256")
HMAC_TOLERANCE_SEC        = int(os.getenv("HMAC_TOLERANCE_SEC", os.getenv("ANTI_REPLAY_SKEW_SEC", "60")) or 60)
HMAC_NONCE_TTL_SEC        = int(os.getenv("HMAC_NONCE_TTL_SEC", os.getenv("ANTI_REPLAY_NONCE_TTL_SEC", "180")) or 180)
HMAC_NAMESPACE            = (os.getenv("HMAC_NAMESPACE", "hmac") or "hmac").strip()

# secret resolution (in priority order)
HMAC_SECRET = (
    os.getenv("API_SIGNING_SECRET") or
    os.getenv("WEBHOOK_HMAC_SECRET") or
    os.getenv("OPS_SIGN_SECRET") or
    ""
).strip()

# optional Redis (for nonce replay-protection; fail-open if absent)
_aioredis = None
try:
    import redis.asyncio as _aioredis  # type: ignore
except Exception:
    _aioredis = None

REDIS_URL = (os.getenv("REDIS_URL") or os.getenv("ALGOGPT_REDIS_URL") or "").strip()
_redis_client = None
_client_lock = asyncio.Lock()

async def _get_redis():
    global _redis_client
    if not (_aioredis and REDIS_URL):
        return None
    if _redis_client:
        return _redis_client
    async with _client_lock:
        if _redis_client:
            return _redis_client
        try:
            _redis_client = _aioredis.from_url(REDIS_URL, decode_responses=True, health_check_interval=15)
        except Exception as e:
            logger.warning("hmac: redis connect failed: %s", e)
            _redis_client = None
    return _redis_client

def _as_key(secret_hex_or_text: str) -> bytes:
    # support 64-hex; otherwise treat as utf-8 text
    try:
        if len(secret_hex_or_text) == 64:
            return bytes.fromhex(secret_hex_or_text)
    except Exception:
        pass
    return secret_hex_or_text.encode("utf-8")

def _canon(method: str, path: str, query: str, ts: str, body_sha256: str) -> bytes:
    # newline-separated canonical string; simple & robust
    return "\n".join([method.upper(), path, query or "", ts, body_sha256]).encode("utf-8")

def _digest_hex(secret: str, payload: bytes) -> str:
    return hmac.new(_as_key(secret), payload, hashlib.sha256).hexdigest()

def _strip_sig_prefix(sig: str) -> str:
    # accept "sha256=<hex>" or bare hex
    s = sig.strip()
    if s.lower().startswith("sha256="):
        return s.split("=", 1)[1].strip()
    return s

async def _nonce_check_once(nonce: Optional[str], ttl: int) -> bool:
    if not nonce:
        # nonce optional; when missing, allow (you can force by setting HMAC_NONCE_REQUIRED=1 later if תרצה)
        return True
    r = await _get_redis()
    if not r:
        return True  # fail-open
    key = f"{HMAC_NAMESPACE}:nonce:{nonce}"
    try:
        ok = await r.setnx(key, "1")
        if ok:
            await r.expire(key, max(60, int(ttl)))
        return bool(ok)
    except Exception as e:
        logger.debug("nonce check failed (permissive): %s", e)
        return True

async def verify_request_signature(request: Request) -> Tuple[bool, str]:
    """Core verifier; returns (ok, reason)."""
    if not HMAC_ENABLE:
        return True, "disabled"
    if not HMAC_SECRET:
        return (True, "no_secret") if not HMAC_REQUIRE else (False, "secret_missing")

    sig_hdr = request.headers.get(HMAC_HEADER, "")
    ts_hdr  = request.headers.get(HMAC_TS_HEADER, "")
    nonce   = request.headers.get(HMAC_NONCE_HEADER, "")
    body_hash_hdr = request.headers.get(HMAC_BODY_HASH_HEADER, "")

    if not sig_hdr:
        return (True, "no_signature_header") if not HMAC_REQUIRE else (False, "signature_missing")
    if not ts_hdr:
        return (True, "no_timestamp_header") if not HMAC_REQUIRE else (False, "timestamp_missing")

    # timestamp tolerance
    try:
        ts_num = int(ts_hdr)
    except Exception:
        return False, "bad_timestamp"
    now = int(time.time())
    if abs(now - ts_num) > max(0, HMAC_TOLERANCE_SEC):
        return False, "timestamp_out_of_window"

    # raw elements
    method = request.method.upper()
    path   = request.url.path
    query  = request.url.query or ""

    # body
    try:
        body = await request.body()
    except Exception:
        body = b""
    body_sha = body_hash_hdr.strip().lower() or hashlib.sha256(body).hexdigest()

    payload = _canon(method, path, query, str(ts_num), body_sha)
    expected = _digest_hex(HMAC_SECRET, payload)
    supplied = _strip_sig_prefix(sig_hdr).lower()

    if not hmac.compare_digest(expected, supplied):
        return False, "signature_mismatch"

    # nonce replay-protection (best effort)
    ok_nonce = await _nonce_check_once(nonce, HMAC_NONCE_TTL_SEC)
    if not ok_nonce:
        return False, "replay_nonce"

    return True, "ok"

# ===== FastAPI dependency =====
async def hmac_verify(request: Request) -> None:
    ok, reason = await verify_request_signature(request)
    if not ok:
        # keep clear but terse errors; do not leak the expected signature
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "hmac_unauthorized", "reason": reason},
        )


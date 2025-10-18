# utils/anti_replay.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, hmac, hashlib, json, threading
from typing import Optional, Tuple, Any, Dict
from contextlib import suppress

# Optional Redis (preferred)
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

_NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
_REDIS_URL = (os.getenv("REDIS_URL") or os.getenv("ALGOGPT_REDIS_URL") or "").strip()
_SECRET = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()

# Policy
_ENABLE = os.getenv("ANTI_REPLAY_ENABLE", "1").lower() in ("1", "true", "yes", "on")
_REQUIRE_SIGNATURE_DEFAULT = os.getenv("ANTI_REPLAY_REQUIRE_SIGNATURE", "0").lower() in ("1", "true", "yes", "on")
_SKEW_SEC = int(os.getenv("ANTI_REPLAY_SKEW_SEC", "120") or 120)          # ±seconds
_NONCE_TTL_SEC = int(os.getenv("ANTI_REPLAY_NONCE_TTL_SEC", "600") or 600)

# Local fallback store (best-effort)
_mem_lock = threading.Lock()
_mem_nonces: Dict[str, float] = {}  # key -> expiry_ts

async def _get_redis():
    if not (aioredis and _REDIS_URL):
        return None
    r = getattr(_get_redis, "_r", None)
    if r:
        return r
    r = aioredis.from_url(_REDIS_URL, decode_responses=True)
    setattr(_get_redis, "_r", r)
    return r

def _sha256_hex(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()

def _hmac_hex(secret_hex_or_text: str, payload: bytes) -> str:
    # Allow 64-hex key or raw utf-8 text key
    try:
        key = bytes.fromhex(secret_hex_or_text) if len(secret_hex_or_text) == 64 else secret_hex_or_text.encode("utf-8")
    except ValueError:
        key = secret_hex_or_text.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

def _now() -> int:
    return int(time.time())

def _mem_claim_once(key: str, ttl_sec: int) -> bool:
    with _mem_lock:
        now = time.time()
        # GC small sweep
        to_del = [k for k, exp in _mem_nonces.items() if exp <= now]
        for k in to_del:
            _mem_nonces.pop(k, None)
        if key in _mem_nonces:
            return False
        _mem_nonces[key] = now + ttl_sec
        return True

def _build_base(route: str, ts: str, nonce: str, body: Any) -> bytes:
    # Canonical base string for signature (no HTTP method available in current API)
    # If you later add method/query—append deterministically here.
    body_bytes: bytes
    if body is None:
        body_bytes = b""
    elif isinstance(body, (bytes, bytearray)):
        body_bytes = bytes(body)
    elif isinstance(body, str):
        body_bytes = body.encode("utf-8")
    else:
        with suppress(Exception):
            return f"{route}|{ts}|{nonce}|{_NS}|{_sha256_hex(json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))}".encode("utf-8")
        body_bytes = b""
    return f"{route}|{ts}|{nonce}|{_NS}|{_sha256_hex(body_bytes)}".encode("utf-8")

async def _claim_nonce_global(nonce: str, ttl_sec: int) -> bool:
    # Prefer Redis NX+EX, fallback to memory
    key = f"{_NS}:anti_replay:nonce:{nonce}"
    r = await _get_redis()
    if r:
        try:
            ok = await r.set(key, "1", nx=True, ex=int(ttl_sec))
            return bool(ok)
        except Exception:
            pass
    return _mem_claim_once(key, ttl_sec)

async def verify_request(
    ts_header: Optional[str],
    nonce_header: Optional[str],
    signature_header: Optional[str],
    route: str,
    body: Any,
    require_signature: bool = False
) -> Tuple[bool, str]:
    """
    Returns (ok, reason). If _ENABLE is False -> permissive allow (ok, 'disabled').
    Policy:
      - If require_signature or _REQUIRE_SIGNATURE_DEFAULT is True: signature must be present & valid.
      - Timestamp must be within ±_SKEW_SEC.
      - Nonce must be unique for _NONCE_TTL_SEC.

    Headers (by caller): ts_header, nonce_header, signature_header (hex SHA256 HMAC).
    Route: the path string e.g. '/ops/approve'.
    """
    if not _ENABLE:
        return True, "disabled"

    # Policy resolve
    must_sign = require_signature or _REQUIRE_SIGNATURE_DEFAULT

    # Basic fields
    ts_s = (ts_header or "").strip()
    nonce = (nonce_header or "").strip()
    sig = (signature_header or "").strip()

    # TS check
    try:
        ts_i = int(ts_s)
    except Exception:
        if must_sign:
            return False, "bad_ts"
        else:
            # soft allow when not required
            ts_i = _now()

    now = _now()
    if abs(now - ts_i) > _SKEW_SEC:
        if must_sign:
            return False, "ts_skew"
        # soft allow if not required
    # Signature check
    if must_sign:
        if not (_SECRET and sig and nonce and ts_s):
            return False, "missing_sig_or_secret"
        base = _build_base(route, ts_s, nonce, body)
        expected = _hmac_hex(_SECRET, base)
        if not hmac.compare_digest(expected, sig):
            return False, "bad_sig"

    # Nonce claim (prevents replay). If missing nonce and must_sign: block. Otherwise best-effort.
    if must_sign and not nonce:
        return False, "missing_nonce"
    if nonce:
        claimed = await _claim_nonce_global(nonce, _NONCE_TTL_SEC)
        if not claimed:
            return False, "replay"

    return True, "ok"



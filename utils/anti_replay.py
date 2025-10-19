# utils/anti_replay.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, hmac, hashlib, json, threading, asyncio
from typing import Optional, Tuple, Any, Dict
from contextlib import suppress

# Optional Redis (preferred): both sync and asyncio clients supported
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:  # pragma: no cover
    aioredis = None  # type: ignore

try:
    import redis as rsync  # type: ignore
except Exception:  # pragma: no cover
    rsync = None  # type: ignore

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

# ---------- Redis helpers ----------
_async_redis_cached = None
_sync_redis_cached = None

async def _get_redis_async():
    global _async_redis_cached
    if not (aioredis and _REDIS_URL):
        return None
    if _async_redis_cached:
        return _async_redis_cached
    _async_redis_cached = aioredis.from_url(_REDIS_URL, decode_responses=True)
    return _async_redis_cached

def _get_redis_sync():
    global _sync_redis_cached
    if not (rsync and _REDIS_URL):
        return None
    if _sync_redis_cached:
        return _sync_redis_cached
    _sync_redis_cached = rsync.from_url(_REDIS_URL, decode_responses=True, socket_timeout=3.0)
    return _sync_redis_cached

# ---------- misc helpers ----------
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

def _canonicalize_body(body: Any) -> bytes:
    if body is None:
        return b""
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    if isinstance(body, str):
        return body.encode("utf-8")
    # dict/list/other json-serializable
    try:
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except Exception:
        return b""

def _build_base(route: str, ts: str, nonce: str, body: Any) -> bytes:
    """
    Canonical base string for signature:
    {route}|{ts}|{nonce}|{namespace}|{sha256(body)}
    """
    body_bytes = _canonicalize_body(body)
    return f"{route}|{ts}|{nonce}|{_NS}|{_sha256_hex(body_bytes)}".encode("utf-8")

# ---------- nonce claimers ----------
def _claim_nonce_global_sync(nonce: str, ttl_sec: int) -> bool:
    key = f"{_NS}:anti_replay:nonce:{nonce}"
    r = _get_redis_sync()
    if r:
        try:
            ok = r.set(key, "1", nx=True, ex=int(ttl_sec))
            return bool(ok)
        except Exception:
            # fall back to memory
            pass
    return _mem_claim_once(key, ttl_sec)

async def _claim_nonce_global_async(nonce: str, ttl_sec: int) -> bool:
    key = f"{_NS}:anti_replay:nonce:{nonce}"
    r = await _get_redis_async()
    if r:
        try:
            ok = await r.set(key, "1", nx=True, ex=int(ttl_sec))
            return bool(ok)
        except Exception:
            pass
    return _mem_claim_once(key, ttl_sec)

# ---------- core logic (shared) ----------
def _verify_fields(ts_header: Optional[str],
                   nonce_header: Optional[str],
                   signature_header: Optional[str],
                   route: str,
                   body: Any,
                   require_signature: bool) -> Tuple[bool, str, int, str, str, bytes]:
    """
    Returns tuple: (ok, reason, ts_i, ts_s, nonce, base_bytes)
    If ok=False -> early reason.
    """
    if not _ENABLE:
        return True, "disabled", _now(), "", "", b""

    must_sign = require_signature or _REQUIRE_SIGNATURE_DEFAULT

    ts_s = (ts_header or "").strip()
    nonce = (nonce_header or "").strip()
    sig = (signature_header or "").strip()

    # Timestamp
    try:
        ts_i = int(ts_s)
    except Exception:
        if must_sign:
            return False, "bad_ts", 0, ts_s, nonce, b""
        ts_i = _now()

    now = _now()
    if abs(now - ts_i) > _SKEW_SEC:
        if must_sign:
            return False, "ts_skew", ts_i, ts_s, nonce, b""
        # soft-allow otherwise

    # Signature
    if must_sign:
        if not (_SECRET and sig and nonce and ts_s):
            return False, "missing_sig_or_secret", ts_i, ts_s, nonce, b""
        base = _build_base(route, ts_s, nonce, body)
        expected = _hmac_hex(_SECRET, base)
        if not hmac.compare_digest(expected, sig):
            return False, "bad_sig", ts_i, ts_s, nonce, base
        return True, "ok", ts_i, ts_s, nonce, base

    base = _build_base(route, ts_s, nonce, body)  # built anyway for parity/logs
    return True, "ok", ts_i, ts_s, nonce, base

# ---------- public (sync) ----------
def verify_request(
    ts_header: Optional[str],
    nonce_header: Optional[str],
    signature_header: Optional[str],
    route: str,
    body: Any,
    require_signature: bool = False
) -> Tuple[bool, str]:
    """
    Synchronous verifier — safe to call from regular FastAPI endpoints.
    Uses sync Redis if configured, else in-memory fallback.
    """
    ok, reason, _ts_i, _ts_s, nonce, _base = _verify_fields(
        ts_header, nonce_header, signature_header, route, body, require_signature
    )
    if not ok:
        return ok, reason

    # Nonce claim
    if (_REQUIRE_SIGNATURE_DEFAULT or require_signature) and not nonce:
        return False, "missing_nonce"
    if nonce:
        claimed = _claim_nonce_global_sync(nonce, _NONCE_TTL_SEC)
        if not claimed:
            return False, "replay"

    return True, "ok"

# ---------- public (async) ----------
async def verify_request_async(
    ts_header: Optional[str],
    nonce_header: Optional[str],
    signature_header: Optional[str],
    route: str,
    body: Any,
    require_signature: bool = False
) -> Tuple[bool, str]:
    """
    Async variant. If you run in an async context and prefer aioredis, use this.
    """
    ok, reason, _ts_i, _ts_s, nonce, _base = _verify_fields(
        ts_header, nonce_header, signature_header, route, body, require_signature
    )
    if not ok:
        return ok, reason

    if (_REQUIRE_SIGNATURE_DEFAULT or require_signature) and not nonce:
        return False, "missing_nonce"
    if nonce:
        claimed = await _claim_nonce_global_async(nonce, _NONCE_TTL_SEC)
        if not claimed:
            return False, "replay"

    return True, "ok"


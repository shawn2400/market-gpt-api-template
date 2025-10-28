# utils/anti_replay.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

# -------- Optional Redis (preferred) --------
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:  # pragma: no cover
    aioredis = None  # type: ignore

try:
    import redis as rsync  # type: ignore
except Exception:  # pragma: no cover
    rsync = None  # type: ignore

# -------- Config / ENV --------
_NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
_REDIS_URL = (os.getenv("REDIS_URL") or os.getenv("ALGOGPT_REDIS_URL") or "").strip()

# Secret selection priority (kept as-is for backward compatibility)
_SECRET = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()
_SECRET_SRC = "WEBHOOK_HMAC_SECRET" if os.getenv("WEBHOOK_HMAC_SECRET") else ("OPS_SIGN_SECRET" if os.getenv("OPS_SIGN_SECRET") else "")

# Policy
_ENABLE = os.getenv("ANTI_REPLAY_ENABLE", "1").lower() in ("1", "true", "yes", "on")
_REQUIRE_SIGNATURE_DEFAULT = os.getenv("ANTI_REPLAY_REQUIRE_SIGNATURE", "0").lower() in ("1", "true", "yes", "on")
_SKEW_SEC = int(os.getenv("ANTI_REPLAY_SKEW_SEC", "120") or 120)          # ± seconds
_NONCE_TTL_SEC = int(os.getenv("ANTI_REPLAY_NONCE_TTL_SEC", "600") or 600)

# HTTP Signatures: which header names we accept for ts/nonce/body hash (case-insensitive)
_TS_HEADER_CANDIDATES = ("x-request-timestamp", "x-ops-timestamp")
_NONCE_HEADER_CANDIDATES = ("x-request-nonce", "x-ops-nonce")
# Body hash candidates we can validate (case-insensitive keys)
_BODYHASH_HEADER_CANDIDATES = ("digest", "x-content-sha256", "content-digest")

logger = logging.getLogger("anti_replay")

# -------- Local fallback store (best-effort) --------
_mem_lock = threading.Lock()
_mem_nonces: Dict[str, float] = {}  # key -> expiry_ts

# -------- Redis helpers --------
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

# -------- misc helpers --------
def _now() -> int:
    return int(time.time())

def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _sha256_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")

def _canonicalize_body(body: Any) -> bytes:
    """Return UTF-8 bytes for body in a canonical way (no trailing newline)."""
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

def _lowerkey_headers(h: Dict[str, str]) -> Dict[str, str]:
    return {(k or "").lower(): v for k, v in (h or {}).items()}

def _select_key_bytes(secret_hex_or_text: str) -> bytes:
    """
    If 64-hex -> interpret as hex key (32B).
    Otherwise treat as raw UTF-8 text key (ASCII key).
    """
    try:
        if len(secret_hex_or_text) == 64 and all(c in "0123456789abcdefABCDEF" for c in secret_hex_or_text):
            return bytes.fromhex(secret_hex_or_text)
    except Exception:
        pass
    return secret_hex_or_text.encode("utf-8")

def _hmac_bytes(secret_hex_or_text: str, payload: bytes) -> bytes:
    key = _select_key_bytes(secret_hex_or_text)
    hm = hmac.new(key, payload, hashlib.sha256).digest()
    return hm

def _hmac_hex(secret_hex_or_text: str, payload: bytes) -> str:
    return _hmac_bytes(secret_hex_or_text, payload).hex()

def _hmac_b64(secret_hex_or_text: str, payload: bytes) -> str:
    return base64.b64encode(_hmac_bytes(secret_hex_or_text, payload)).decode("ascii")

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

# -------- nonce claimers --------
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

# -------- OLD (internal) scheme: "route|ts|nonce|ns|sha256(body)" in HEX --------
def _build_internal_base(route: str, ts: str, nonce: str, body: Any) -> bytes:
    """
    Canonical base string for legacy/internal signature:
    {route}|{ts}|{nonce}|{namespace}|{sha256(body)}
    Signature expected as hex string.
    """
    body_bytes = _canonicalize_body(body)
    return f"{route}|{ts}|{nonce}|{_NS}|{_sha256_hex(body_bytes)}".encode("utf-8")

def _verify_fields_internal(
    ts_header: Optional[str],
    nonce_header: Optional[str],
    signature_header: Optional[str],
    route: str,
    body: Any,
    require_signature: bool,
) -> Tuple[bool, str, int, str, str, bytes]:
    """
    Returns tuple: (ok, reason, ts_i, ts_s, nonce, base_bytes)
    If ok=False -> early reason (e.g., bad_ts, ts_skew, missing_sig_or_secret, bad_sig).
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
        base = _build_internal_base(route, ts_s, nonce, body)
        expected_hex = _hmac_hex(_SECRET, base)
        # signature_header is expected HEX for this internal mode
        if not hmac.compare_digest(expected_hex, sig):
            return False, "bad_sig", ts_i, ts_s, nonce, base
        return True, "ok", ts_i, ts_s, nonce, base

    base = _build_internal_base(route, ts_s, nonce, body)  # built anyway
    return True, "ok", ts_i, ts_s, nonce, base

# -------- HTTP Signatures (RFC style) support --------
def _parse_signature_header(h: str) -> Dict[str, str]:
    """
    Parse Authorization: Signature keyId="...",algorithm="...",headers="...",signature="..."
    Returns dict with keys: keyId, algorithm, headers, signature
    """
    out: Dict[str, str] = {}
    if not h:
        return out
    # Allow both "Signature ..." and value only
    txt = h.strip()
    if txt.lower().startswith("signature "):
        txt = txt[len("signature "):].strip()

    # Split by comma at top-level (simple parser; values are quoted)
    parts: List[str] = []
    cur: List[str] = []
    in_q = False
    for ch in txt:
        if ch == '"' and (not cur or cur[-1] != '\\'):
            in_q = not in_q
            cur.append(ch)
        elif ch == ',' and not in_q:
            parts.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append(''.join(cur).strip())

    for p in parts:
        if '=' not in p:
            continue
        k, v = p.split('=', 1)
        k = k.strip().lower()
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        out[k] = v
    return out

def _http_sig_build_string_to_sign(
    method: str,
    route_path: str,
    headers: Dict[str, str],
    headers_list: Iterable[str],
) -> str:
    """
    Build the string-to-sign exactly as per `headers="..."` list.
    Lower-case header names; `(request-target)` -> "<method-lower> <route_path>"
    Lines joined by "\n" with NO trailing newline.
    """
    h = _lowerkey_headers(headers)
    m = (method or "GET").lower()
    lines: List[str] = []
    for hn in headers_list:
        hn_l = hn.strip().lower()
        if hn_l == "(request-target)":
            lines.append(f"(request-target): {m} {route_path}")
        else:
            val = h.get(hn_l, "")
            lines.append(f"{hn_l}: {val}")
    return "\n".join(lines)

def _http_sig_expected_b64(
    method: str,
    route_path: str,
    headers: Dict[str, str],
    headers_list: Iterable[str],
) -> str:
    sts = _http_sig_build_string_to_sign(method, route_path, headers, headers_list).encode("utf-8")
    key = _select_key_bytes(_SECRET)
    return base64.b64encode(hmac.new(key, sts, hashlib.sha256).digest()).decode("ascii")

def _extract_first(headers: Dict[str, str], names: Iterable[str]) -> Optional[str]:
    h = _lowerkey_headers(headers)
    for n in names:
        if n.lower() in h and h[n.lower()]:
            return h[n.lower()]
    return None

def _validate_body_hash_if_present(headers: Dict[str, str], body_bytes: bytes) -> Tuple[bool, str, bool]:
    """
    Validates optional body hash headers, if present.
    Supports:
      - Digest: "SHA-256=<base64>"
      - X-Content-SHA256: "<base64>"
      - Content-Digest (RFC 9530): "sha-256=:<base64>:" possibly among multiple algs
    Returns (ok, reason, validated)
    """
    h = _lowerkey_headers(headers or {})
    validated = False

    # Digest
    if "digest" in h and h["digest"]:
        dv = h["digest"].strip()
        if not dv.upper().startswith("SHA-256="):
            return False, "bad_digest_format", validated
        b64 = dv.split("=", 1)[1]
        if b64 != _sha256_b64(body_bytes):
            return False, "bad_digest_mismatch", validated
        validated = True

    # X-Content-SHA256
    if "x-content-sha256" in h and h["x-content-sha256"]:
        if h["x-content-sha256"].strip() != _sha256_b64(body_bytes):
            return False, "bad_xcontentsha_mismatch", validated
        validated = True

    # Content-Digest (RFC 9530)
    if "content-digest" in h and h["content-digest"]:
        # Example: sha-256=:<base64>:
        try:
            import re
            v = h["content-digest"]
            m = re.search(r"sha-256\s*=\s*:(?P<b64>[A-Za-z0-9+/=]+):", v)
            if not m:
                return False, "bad_content_digest_format", validated
            want_b64 = m.group("b64")
            if want_b64 != _sha256_b64(body_bytes):
                return False, "bad_content_digest_mismatch", validated
            validated = True
        except Exception:
            return False, "bad_content_digest_format", validated

    return True, "ok", validated

def _verify_http_signature_common(
    method: str,
    route_path: str,
    headers: Dict[str, str],
    body: Any,
    require_signature: bool,
) -> Tuple[bool, str]:
    """
    Verify an HTTP Signatures-style request.
    - signature is Base64 HMAC-SHA256 over the string-to-sign built from "headers=...".
    - Timestamp/nonce skew and anti-replay enforced if require_signature or default is on.
    """
    if not _ENABLE:
        return True, "disabled"

    if not _SECRET:
        return False, "missing_secret"

    must_sign = require_signature or _REQUIRE_SIGNATURE_DEFAULT
    h = _lowerkey_headers(headers or {})

    auth = (h.get("authorization") or "").strip()
    if not auth and must_sign:
        return False, "missing_authorization"

    # Parse Signature header
    d = _parse_signature_header(auth)
    sig_b64 = d.get("signature", "")
    headers_list_raw = d.get("headers", "")
    algorithm = (d.get("algorithm", "") or "").lower()
    key_id = d.get("keyid", "")
    if not (sig_b64 and headers_list_raw):
        if must_sign:
            return False, "missing_sig_fields"
        else:
            return True, "ok"

    if algorithm and algorithm != "hmac-sha256":
        # We only support HMAC-SHA256
        return False, "bad_algorithm"

    headers_list = [p for p in headers_list_raw.strip().split() if p]

    # Timestamp + Nonce (must appear either as x-request-* או x-ops-*)
    ts_val = _extract_first(h, _TS_HEADER_CANDIDATES)
    nonce_val = _extract_first(h, _NONCE_HEADER_CANDIDATES)

    # Check skew
    if ts_val:
        try:
            ts_i = int(ts_val.strip())
        except Exception:
            return False, "bad_ts"
        if abs(_now() - ts_i) > _SKEW_SEC:
            return False, "ts_skew"
    else:
        if must_sign:
            return False, "missing_ts"

    if not nonce_val and must_sign:
        return False, "missing_nonce"

    # Optional body-hash validation if present (accept any of the supported headers)
    body_bytes = _canonicalize_body(body)
    ok_hash, reason_hash, _validated = _validate_body_hash_if_present(h, body_bytes)
    if not ok_hash:
        return False, reason_hash

    # Build expected signature (Base64) exactly per headers=
    try:
        expected_b64 = _http_sig_expected_b64(method, route_path, h, headers_list)
    except Exception:
        return False, "sig_build_error"

    if not hmac.compare_digest(expected_b64, sig_b64):
        return False, "bad_sig"

    # Anti-replay for nonce (only if present)
    if nonce_val:
        if not _claim_nonce_global_sync(nonce_val, _NONCE_TTL_SEC):
            return False, "replay"

    # Everything ok
    try:
        logger.info(
            "anti-replay: HTTP-SIG ok keyId=%s secret_src=%s headers=%s ts=%s nonce=%s",
            key_id, _SECRET_SRC, headers_list, ts_val, nonce_val
        )
    except Exception:
        pass

    return True, "ok"

# -------- PUBLIC API (SYNC/ASYNC) --------
def verify_request(
    ts_header: Optional[str],
    nonce_header: Optional[str],
    signature_header: Optional[str],
    route: str,
    body: Any,
    require_signature: bool = False
) -> Tuple[bool, str]:
    """
    Legacy/internal verifier — for endpoints that still use simple headers:
      - ts_header: string timestamp (epoch seconds)
      - nonce_header: random hex
      - signature_header: HEX of HMAC( route|ts|nonce|namespace|sha256(body) )
    If you want HTTP Signatures verification, use `verify_http_signature(...)`.
    """
    ok, reason, _ts_i, _ts_s, nonce, _base = _verify_fields_internal(
        ts_header, nonce_header, signature_header, route, body, require_signature
    )
    if not ok:
        return ok, reason

    # Nonce claim (legacy path)
    if (_REQUIRE_SIGNATURE_DEFAULT or require_signature) and not nonce:
        return False, "missing_nonce"
    if nonce:
        claimed = _claim_nonce_global_sync(nonce, _NONCE_TTL_SEC)
        if not claimed:
            return False, "replay"

    return True, "ok"

async def verify_request_async(
    ts_header: Optional[str],
    nonce_header: Optional[str],
    signature_header: Optional[str],
    route: str,
    body: Any,
    require_signature: bool = False
) -> Tuple[bool, str]:
    ok, reason, _ts_i, _ts_s, nonce, _base = _verify_fields_internal(
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

# -------- PUBLIC API: HTTP Signatures (recommended) --------
def verify_http_signature(
    method: str,
    route_path: str,
    headers: Dict[str, str],
    body: Any,
    require_signature: bool = True,
) -> Tuple[bool, str]:
    """
    Verify an HTTP Signatures style request.
      method: HTTP method (e.g., "POST")
      route_path: e.g., "/ops/approve/signed"  (MUST match what the client used in (request-target))
      headers: request headers (case-insensitive keys are handled)
      body: raw string/bytes or JSON-serializable object (canonicalized internally)
    """
    return _verify_http_signature_common(method, route_path, headers, body, require_signature)

async def verify_http_signature_async(
    method: str,
    route_path: str,
    headers: Dict[str, str],
    body: Any,
    require_signature: bool = True,
) -> Tuple[bool, str]:
    ok, reason = _verify_http_signature_common(method, route_path, headers, body, require_signature)
    # Anti-replay already handled inside common path (sync claim). If you prefer async Redis, swap here.
    return ok, reason



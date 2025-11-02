# -*- coding: utf-8 -*-
from __future__ import annotations
import hmac, hashlib, time, os, re
from typing import Any, Tuple, Optional, Union

# ========= Helper functions exported for backward compatibility =========
def _b(s: Union[str, bytes]) -> bytes:
    """Convert string to bytes"""
    return s if isinstance(s, (bytes, bytearray)) else str(s).encode("utf-8", "ignore")

def _sha256_hex(data: bytes) -> str:
    """SHA256 hash of bytes, returns hex string"""
    return hashlib.sha256(data).hexdigest()

def _canon(s: str) -> str:
    """Canonicalize small tokens safely (tolerant, stable)."""
    if s is None:
        return ""
    s = str(s).strip()
    # Normalize whitespace
    s = re.sub(r"\s+", " ", s)
    return s

def _ct_equal(a: str, b: str) -> bool:
    """Constant-time string comparison"""
    try:
        return hmac.compare_digest(a or "", b or "")
    except Exception:
        return (a or "") == (b or "")

def _hexdigest(secret: str, msg: str) -> str:
    """HMAC SHA256 hex digest"""
    return hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()

def _short(sig_hex: str, n: int = 6) -> str:
    """Get first N hex chars of signature"""
    return (sig_hex or "")[:max(1, n)]

def _now() -> int:
    """Current Unix timestamp"""
    return int(time.time())

def _ttl_ok(ts: int, ttl: int, skew: int = 15) -> bool:
    """Check if timestamp is within TTL window"""
    now = _now()
    return (ts >= now - (ttl + skew)) and (ts <= now + skew)

# ========= Telegram callback payload verification =========
# Format observed in logs:
#   CONFIRM:APPROVE:TKT-xxx:1762088032:26fa87
# 
# Tolerant verifier: supports both full signature (64 hex) and short prefix (6 hex).
#
# Canonicalization:
#   base = f"{action}:{decision}:{ticket}:{ts}"
#   sig  = HMAC_SHA256(secret, base)
#
def verify_telegram_callback_payload(payload: str,
                                     secret: Optional[str] = None,
                                     ttl_sec: int = 900) -> Tuple[bool, str]:
    """
    Verify Telegram callback button signatures with multi-base tolerance.
    
    Args:
        payload: Format "CONFIRM:ACTION:TICKET:TIMESTAMP:SIGNATURE"
        secret: HMAC secret (defaults to env vars)
        ttl_sec: Time-to-live in seconds
        
    Returns:
        (is_valid, reason)
    """
    if not payload or ":" not in payload:
        return False, "malformed"
    
    parts = str(payload).split(":")
    if len(parts) < 5:
        return False, "parts_lt_5"
    
    # Extract parts (matching SmartSignature format)
    # Format: CONFIRM:APPROVE:TKT-xxx:timestamp:sig
    sig_in = parts[-1]  # Last part is signature
    ts_str = parts[-2]  # Second-to-last is timestamp

    # Validate timestamp
    try:
        ts = int(ts_str)
    except Exception:
        return False, "bad_ts"
    
    if not _ttl_ok(ts, ttl_sec):
        return False, "expired_or_future_ts"

    # Get secret from env
    sec = secret or os.getenv("OPS_SIGN_SECRET") or os.getenv("AI_MESH_SECRET") or os.getenv("API_SIGNING_SECRET") or ""
    if not sec:
        return False, "missing_secret"

    # Build canonical base (matching SmartSignature: all parts except signature)
    # This matches: raw = ":".join(parts[:-1]) from SmartSignature
    raw = ":".join(parts[:-1])

    # Verify: match full signature or 4/6/8 char prefix (SmartSignature uses 4/6/8)
    full = _hexdigest(sec, raw)
    if (_ct_equal(sig_in, full) or 
        _ct_equal(sig_in, _short(full, 4)) or 
        _ct_equal(sig_in, _short(full, 6)) or 
        _ct_equal(sig_in, _short(full, 8))):
        return True, "ok"
    
    return False, "bad_sig"


# ========= General request verification (for API endpoints) =========
def verify_request(
    ts_header: str | None,
    nonce_header: str | None,
    signature_header: str | None,
    route: str,
    body: Any,
    require_signature: bool = False
) -> Tuple[bool, str]:
    """
    Verify signed API requests with HMAC.
    
    Args:
        ts_header: Unix timestamp header
        nonce_header: Nonce/node ID header
        signature_header: HMAC signature header
        route: API route path
        body: Request body
        require_signature: Whether signature is mandatory
        
    Returns:
        (is_valid, reason)
    """
    if not require_signature:
        return True, "ok"

    sec = os.getenv("API_SIGNING_SECRET") or os.getenv("OPS_SIGN_SECRET") or os.getenv("AI_MESH_SECRET") or ""
    if not sec:
        return False, "missing_secret"

    # Validate timestamp
    try:
        ts = int((ts_header or "0").strip())
    except Exception:
        return False, "bad_ts"
    
    ttl = int(os.getenv("SIGN_TTL_SEC", "900"))
    if not _ttl_ok(ts, ttl):
        return False, "expired_or_future_ts"

    # Build canonical message
    nonce = _canon(nonce_header or "")
    body_s = _canon(str(body or ""))
    bh = hashlib.sha256(body_s.encode("utf-8")).hexdigest()
    base = f"{_canon(route)}|{ts}|{nonce}|{bh}"
    
    # Verify signature
    want = _hexdigest(sec, base)
    got = (signature_header or "")
    
    if _ct_equal(got, want) or _ct_equal(got, _short(want, 12)):
        return True, "ok"
    
    return False, "bad_sig"


# Export all public functions
__all__ = [
    "verify_request",
    "verify_telegram_callback_payload",
    "_canon",
    "_sha256_hex",
    "_b",
    "_ct_equal",
    "_hexdigest",
    "_short",
    "_ttl_ok"
]

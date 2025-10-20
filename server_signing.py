# server_signing.py
from __future__ import annotations
import base64
import hmac
import hashlib
import os
import time
from typing import Tuple

# ENV name for the shared secret. Accepts 64-hex or plain UTF-8 text.
SECRET_ENV = os.environ.get("API_SIGNING_SECRET_ENV", "API_SIGNING_SECRET")

def _load_key(env_name: str = SECRET_ENV) -> bytes:
    raw = os.environ.get(env_name, "") or ""
    if not raw:
        raise RuntimeError(f"{env_name} not set")
    # accept hex or ascii
    try:
        if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
            return bytes.fromhex(raw)
    except Exception:
        pass
    return raw.encode("utf-8")

def _parse_exp(exp_str: str) -> int:
    exp = int(exp_str)
    # support milliseconds (13+ digits)
    if exp > 10**12:
        exp //= 1000
    return exp

def _b64url_no_pad(digest_bytes: bytes) -> str:
    return base64.urlsafe_b64encode(digest_bytes).decode().rstrip("=")

def verify_signature(ticket_id: str, exp_str: str, sig_str: str) -> Tuple[bool, str]:
    """
    Verifies HMAC-SHA256 over the message "{ticket_id}:{exp}".
    Accepts signature either as lowercase/uppercase hex, or base64url (with/without '=' padding).
    Enforces a time window: not expired, and not more than +10m into the future.
    """
    key = _load_key()
    exp = _parse_exp(exp_str)
    now = int(time.time())

    # time window
    if exp < now - 10:             # small negative skew tolerance
        return False, "expired"
    if exp > now + 600:            # max 10 minutes into the future
        return False, "exp too far in future"

    msg = f"{ticket_id}:{exp}".encode("utf-8")
    mac = hmac.new(key, msg, hashlib.sha256)
    digest = mac.digest()
    expected_hex = mac.hexdigest()                 # lowercase hex
    expected_b64 = _b64url_no_pad(digest)         # base64url without padding

    # normalize supplied signature
    supplied = (sig_str or "").strip()

    # hex compare (case-insensitive)
    if hmac.compare_digest(supplied.lower(), expected_hex):
        return True, "ok(hex)"

    # base64url compare: accept with or without padding
    supplied_b64 = supplied.rstrip("=")
    if hmac.compare_digest(supplied_b64, expected_b64):
        return True, "ok(b64url)"

    return False, "bad signature"


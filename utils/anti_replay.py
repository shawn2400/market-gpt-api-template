from __future__ import annotations
import os, hmac, hashlib, time
from typing import Tuple, Union

_SIG_TOLERANCE_SEC = int(os.getenv("SIG_TOLERANCE_SEC", "120"))

def _b(s: Union[str, bytes]) -> bytes:
    return s if isinstance(s, (bytes, bytearray)) else str(s).encode("utf-8", "ignore")

def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _canon(ts: str, nonce: str, route: str, body_bytes: bytes) -> str:
    # Canon: ts \n nonce \n route \n sha256_hex(raw_body)
    return "\n".join([str(ts or ""), str(nonce or ""), str(route or ""), _sha256_hex(body_bytes)])

def _cteq(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest((a or "").lower(), (b or "").lower())
    except Exception:
        return (a or "").lower() == (b or "").lower()

def verify_request(
    ts_header: str | None,
    nonce_header: str | None,
    signature_header: str | None,
    route: str,
    raw_body: Union[bytes, bytearray, str, None],
    require_signature: bool = False
) -> Tuple[bool, str]:
    ts = str(ts_header or "")
    nonce = str(nonce_header or "")
    sig = str(signature_header or "")

    # Allow if not required and headers missing
    if not require_signature and not (ts and nonce and sig):
        return True, "ok"

    if not ts or not nonce or not sig:
        return False, "missing_ts_nonce_or_sig"

    try:
        ts_int = int(ts)
    except Exception:
        return False, "bad_ts_format"

    now = int(time.time())
    if abs(now - ts_int) > _SIG_TOLERANCE_SEC:
        return False, "ts_out_of_window"

    body_bytes = _b(raw_body or b"")
    canon = _canon(ts, nonce, route, body_bytes)

    secret = os.getenv("SIG_SECRET") or os.getenv("API_BEARER_TOKEN") or ""
    if not secret:
        return False, "missing_secret"

    expect = hmac.new(_b(secret), _b(canon), hashlib.sha256).hexdigest()
    if not _cteq(sig, expect):
        return False, "bad_signature"

    return True, "ok"

__all__ = ["verify_request", "_canon", "_sha256_hex", "_b"]

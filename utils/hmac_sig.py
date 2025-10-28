from __future__ import annotations
import hmac, hashlib
from typing import Union

def _b(s: Union[str, bytes]) -> bytes:
    return s if isinstance(s, (bytes, bytearray)) else str(s).encode("utf-8")

def consteq(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a, b)
    except Exception:
        return a == b  # graceful fallback

def compute_signature(secret: str, msg: str, alg: str = "sha256") -> str:
    """
    Compute hex HMAC for msg with secret using alg in {"sha256","sha512"}.
    """
    h = (alg or "sha256").lower()
    if h == "sha512":
        dig = hashlib.sha512
    else:
        h = "sha256"
        dig = hashlib.sha256
    return hmac.new(_b(secret), _b(msg), dig).hexdigest()

def build_signing_string(method: str, path_qs: str, body: Union[str, bytes, None], ts: Union[str, int], nonce: str) -> str:
    """
    Canonical signing string that must match server verification:
    \"\"\"
    <METHOD> <PATH_AND_QUERY>
    <BODY_AS_TEXT>
    ts=<TS>
    nonce=<NONCE>
    \"\"\" 
    """
    m = (method or "GET").upper().strip()
    p = (path_qs or "/").strip()
    if not p.startswith("/"):
        p = "/" + p
    btxt = ""
    if body is not None:
        btxt = body if isinstance(body, str) else body.decode("utf-8", "replace")
    return f"{m} {p}\n{btxt}\nts={ts}\nnonce={nonce}"

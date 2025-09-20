# utils/security.py
from __future__ import annotations
import os, hmac, hashlib, base64
from typing import Optional

from .idempotency import claim as _claim

_SECRET_RAW = os.getenv("WEBHOOK_HMAC_SECRET", "").strip()

def _secret_bytes() -> bytes:
    s = _SECRET_RAW.strip()
    # אם זה מחרוזת hex באורך 64 – ננסה bytes.fromhex
    if len(s) == 64:
        try:
            return bytes.fromhex(s)
        except Exception:
            pass
    # אחרת ASCII כמות־שהוא (התנהגות ישנה)
    return s.encode("utf-8")

def _secret_bytes_ascii() -> bytes:
    # תמיד ASCII (לשימור תאימות ישנה)
    return _SECRET_RAW.encode("utf-8")

def _clean_sig(v: Optional[str]) -> str:
    v = (v or "").strip()
    if v.lower().startswith("sha256="):
        v = v.split("=", 1)[1].strip()
    return v

def verify_hmac(signature_maybe: Optional[str], raw_body: bytes) -> bool:
    """
    אימות HMAC-SHA256 מול שתי וריאציות מפתח:
    1) מפתח HEX מוצהר (new)
    2) מפתח ASCII טהור (old)
    תומך חתימה ב-HEX או Base64, עם/בלי prefix sha256=
    """
    if not _SECRET_RAW:
        return True
    sig = _clean_sig(signature_maybe)
    if not sig:
        return False

    # new: HEX-key
    s_new = _secret_bytes()
    mac_new = hmac.new(s_new, raw_body, hashlib.sha256).digest()
    hex_new = hmac.new(s_new, raw_body, hashlib.sha256).hexdigest()
    b64_new = base64.b64encode(mac_new).decode()

    # old: ASCII-key
    s_old = _secret_bytes_ascii()
    mac_old = hmac.new(s_old, raw_body, hashlib.sha256).digest()
    hex_old = hmac.new(s_old, raw_body, hashlib.sha256).hexdigest()
    b64_old = base64.b64encode(mac_old).decode()

    cand = sig.strip()
    return (
        hmac.compare_digest(cand.lower(), hex_new)
        or hmac.compare_digest(cand, b64_new)
        or hmac.compare_digest(cand.lower(), hex_old)
        or hmac.compare_digest(cand, b64_old)
    )

def idem_seen(key: str) -> bool:
    return not _claim(key)







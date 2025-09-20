# utils/security.py
from __future__ import annotations
import os, hmac, hashlib, base64
from typing import Optional

# נסה לייבא מנגנון idempotency אמיתי; אם אין – נפעיל fallback בזיכרון.
try:
    from .idempotency import claim as _claim
except Exception:
    _SEEN_KEYS: set[str] = set()
    def _claim(key: str) -> bool:
        # True = חדש (נתבע עכשיו); False = כבר נראה (כפילות)
        if key in _SEEN_KEYS:
            return False
        _SEEN_KEYS.add(key)
        return True

_SECRET_RAW = os.getenv("WEBHOOK_HMAC_SECRET", "").strip()

def _secret_bytes() -> bytes:
    """
    מחזיר bytes של הסוד:
    - אם הסוד נראה כמו HEX באורך 64 → bytes.fromhex
    - אחרת ASCII כמות שהוא (תאימות ישנה)
    """
    s = (_SECRET_RAW or "").strip()
    if len(s) == 64:
        try:
            return bytes.fromhex(s)
        except Exception:
            pass
    return s.encode("utf-8")

def _secret_bytes_ascii() -> bytes:
    # תמיד ASCII (לשימור תאימות ישנה)
    return (_SECRET_RAW or "").encode("utf-8")

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

    # new: HEX/ASCII-resolved (מנסה HEX אחרת ASCII)
    s_new = _secret_bytes()
    mac_new = hmac.new(s_new, raw_body, hashlib.sha256).digest()
    hex_new = hmac.new(s_new, raw_body, hashlib.sha256).hexdigest()
    b64_new = base64.b64encode(mac_new).decode()

    # old: ASCII-key מפורש
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

def verify_hmac_multi(raw_body: bytes, *candidates: Optional[str]) -> bool:
    """
    אימות מול מספר כותרות אפשריות (X-Signature / X-Webhook-HMAC / X-Hub-Signature-256).
    חוסך חישובים כפולים ומיישר התנהגות.
    """
    if not _SECRET_RAW:
        return True

    # חשב פעם אחת עבור שני סוגי הסוד
    s_new = _secret_bytes()
    mac_new = hmac.new(s_new, raw_body, hashlib.sha256).digest()
    hex_new = hmac.new(s_new, raw_body, hashlib.sha256).hexdigest()
    b64_new = base64.b64encode(mac_new).decode()

    s_old = _secret_bytes_ascii()
    mac_old = hmac.new(s_old, raw_body, hashlib.sha256).digest()
    hex_old = hmac.new(s_old, raw_body, hashlib.sha256).hexdigest()
    b64_old = base64.b64encode(mac_old).decode()

    for c in candidates:
        c = _clean_sig(c)
        if not c:
            continue
        if (
            hmac.compare_digest(c.lower(), hex_new) or c == b64_new
            or hmac.compare_digest(c.lower(), hex_old) or c == b64_old
        ):
            return True
    return False

def idem_seen(key: str) -> bool:
    """
    True אם כבר ראינו את המפתח (כפילות); False אם חדש.
    (שימו לב: _claim מחזיר True כשמצליח "לתבוע" מפתח חדש; לכן כאן ההיפוך.)
    """
    return not _claim(key)





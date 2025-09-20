# utils/security.py
from __future__ import annotations

import os
import hmac
import hashlib
import base64
import binascii
from typing import Optional, Tuple, Union, Any

# שים את WEBHOOK_HMAC_SECRET ב-ENV
_WEBHOOK_HMAC_SECRET = (os.getenv("WEBHOOK_HMAC_SECRET") or "").strip()


# ===== Idempotency =====
from .idempotency import claim as _claim

def idem_seen(key: str) -> bool:
    """True אם כבר ראינו את המפתח (כפילות); False אם חדש."""
    # _claim(key) -> True אם נתפס עכשיו (חדש); False אם כבר קיים.
    return not _claim(key)


# ===== HMAC helpers =====
def _load_secret() -> Tuple[bytes, str]:
    """
    מחזיר (secret_bytes, mode) כאשר mode ∈ {"hex","ascii","none"}.
    תומך בסוד HEX (כל אורך זוגי תקין) או ASCII רגיל.
    """
    s = _WEBHOOK_HMAC_SECRET
    if not s:
        return b"", "none"
    # נסה לפענח HEX (גם אם אינו בדיוק 64 תווים)
    try:
        if len(s) % 2 == 0:
            return bytes.fromhex(s), "hex"
    except ValueError:
        pass
    return s.encode("utf-8"), "ascii"


def _clean_sig(sig: Optional[str]) -> Optional[str]:
    """מסיר prefix sha256= אם יש ומחזיר מחרוזת 'נקייה'."""
    if not sig:
        return None
    sig = sig.strip()
    if sig.lower().startswith("sha256="):
        sig = sig.split("=", 1)[1].strip()
    return sig


def _compute_digest(body: bytes, secret: bytes) -> bytes:
    return hmac.new(secret, body, hashlib.sha256).digest()


def _match_sig(sig_clean: str, digest: bytes) -> bool:
    """
    בודק התאמה של sig_clean מול ה-digest גם כ-HEX וגם כ-Base64.
    השוואה בזמן קבוע.
    """
    # נסה HEX
    try:
        candidate = binascii.unhexlify(sig_clean.encode("ascii"))
        return hmac.compare_digest(candidate, digest)
    except (binascii.Error, ValueError):
        pass

    # נסה Base64
    try:
        candidate = base64.b64decode(sig_clean, validate=True)
        return hmac.compare_digest(candidate, digest)
    except (binascii.Error, ValueError):
        return False


def verify_hmac(
    signature_value: Optional[str],
    raw_body: Union[bytes, bytearray, memoryview],
    request: Optional[Any] = None,
) -> bool:
    """
    אימות HMAC-SHA256 על גוף הבקשה.
    - קורא חתימה מהפרמטר שקיבל או מהכותרות הבאות (אם הפרמטר ריק):
      X-Signature / X-Webhook-HMAC / X-Hub-Signature-256
    - תומך ב-HEX או Base64, עם/בלי prefix 'sha256='.
    - תומך בסוד HEX או ASCII.
    - אם אין סוד בקונפיג – מחזיר True (לא אוכפים).
    """
    secret, mode = _load_secret()
    if mode == "none":
        return True

    # משוך חתימה
    sig = _clean_sig(signature_value)
    if not sig and request is not None:
        for name in ("x-signature", "x-webhook-hmac", "x-hub-signature-256"):
            v = request.headers.get(name)
            v = _clean_sig(v)
            if v:
                sig = v
                break
    if not sig:
        return False

    # חשב והשווה
    body = bytes(raw_body)
    dig = _compute_digest(body, secret)
    return _match_sig(sig, dig)






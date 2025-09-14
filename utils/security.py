# utils/security.py
from __future__ import annotations
import os, hmac, hashlib
from typing import Optional
from .idempotency import claim as _claim

# שים את WEBHOOK_HMAC_SECRET ב-ENV (ראה הוראות יצירה למעלה)
_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").strip()

def verify_hmac(signature_hex: Optional[str], raw_body: bytes) -> bool:
    """אימות HMAC-SHA256 על גוף הבקשה כולו. True אם תואם או אם אין סוד בקונפיג."""
    if not _SECRET:
        return True
    if not signature_hex:
        return False
    try:
        mac = hmac.new(_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(mac, signature_hex.strip().lower())
    except Exception:
        return False

def idem_seen(key: str) -> bool:
    """True אם כבר ראינו את המפתח (כפילות); False אם חדש."""
    # _claim(key) -> True אם נתפס עכשיו (חדש); False אם כבר קיים.
    return not _claim(key)





# utils/hmac_utils.py
from __future__ import annotations
import hmac, hashlib, os

SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").encode("utf-8")

def verify_inbound(body: bytes, signature: str) -> bool:
    """
    Verify inbound HMAC (SHA256) signature for webhooks.
    Returns True if signature matches, else False.
    """
    if not SECRET:
        return False
    try:
        mac = hmac.new(SECRET, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(mac, signature)
    except Exception:
        return False








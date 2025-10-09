import os, hmac, hashlib, time
from typing import Optional

INBOUND_HMAC_SECRET = os.getenv("INBOUND_HMAC_SECRET", "")  # אופציונלי להגנה על ה-webhook הנכנס
MAX_SKEW_SEC = int(os.getenv("INBOUND_MAX_SKEW_SEC", "60"))  # חלון זמן לבקשה נכנסת

# זיכרון קצר־טווח נגד replay (במכונה בודדת). לפרודקשן אפשר לחבר Redis.
_nonce_store: dict[str, float] = {}

def _is_fresh(ts: str) -> bool:
    try:
        t = float(ts)
    except Exception:
        return False
    return abs(time.time() - t) <= MAX_SKEW_SEC

def check_inbound_signature(ts: str, nonce: str, signature: str, body: bytes) -> bool:
    if not INBOUND_HMAC_SECRET:
        # אם לא הוגדר — לא בודקים חתימה (לא מומלץ לחשיפה ציבורית)
        return True

    # בדיקת חלון זמן
    if not _is_fresh(ts):
        return False

    # Anti-replay בסיסי (in-memory)
    if nonce in _nonce_store and (time.time() - _nonce_store[nonce]) < MAX_SKEW_SEC:
        return False
    _nonce_store[nonce] = time.time()

    # HMAC
    is_hex = (len(INBOUND_HMAC_SECRET) == 64 and all(c in "0123456789abcdefABCDEF" for c in INBOUND_HMAC_SECRET))
    key = bytes.fromhex(INBOUND_HMAC_SECRET) if is_hex else INBOUND_HMAC_SECRET.encode("utf-8")
    msg = f"{ts}.{nonce}.".encode("utf-8") + body
    want = hmac.new(key, msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature or "", want)

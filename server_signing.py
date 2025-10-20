# server_signing.py
from __future__ import annotations
import base64
import hmac
import hashlib
import os
import time
from typing import Tuple

# שם המשתנה שמחזיק את ה־secret. תומך ב־HEX (64 תווים) או טקסט UTF-8 רגיל.
SECRET_ENV = os.environ.get("API_SIGNING_SECRET_ENV", "API_SIGNING_SECRET")

def _load_key(env_name: str = SECRET_ENV) -> bytes:
    raw = os.environ.get(env_name, "") or ""
    if not raw:
        raise RuntimeError(f"{env_name} not set")
    # מאפשר גם hex (64) וגם ascii
    try:
        if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
            return bytes.fromhex(raw)
    except Exception:
        pass
    return raw.encode("utf-8")

def _parse_exp(exp_str: str) -> int:
    exp = int(exp_str)
    # תמיכה ב־ms (13 ספרות ומעלה)
    if exp > 10**12:
        exp //= 1000
    return exp

def _b64url_no_pad(digest_bytes: bytes) -> str:
    return base64.urlsafe_b64encode(digest_bytes).decode().rstrip("=")

def verify_signature(ticket_id: str, exp_str: str, sig_str: str) -> Tuple[bool, str]:
    """
    מאמת HMAC-SHA256 על המסר "{ticket_id}:{exp}".
    חתימה יכולה להיות hex (לא רגיש לאותיות) או base64url (עם/בלי '=').
    חלון זמן: לא פג תוקף, ולא יותר מ־10 דק' קדימה.
    """
    key = _load_key()
    exp = _parse_exp(exp_str)
    now = int(time.time())

    if exp < now - 10:
        return False, "expired"
    if exp > now + 600:
        return False, "exp too far in future"

    msg = f"{ticket_id}:{exp}".encode("utf-8")
    mac = hmac.new(key, msg, hashlib.sha256)
    digest = mac.digest()
    expected_hex = mac.hexdigest()            # hex תחתון
    expected_b64 = _b64url_no_pad(digest)     # base64url בלי padding

    supplied = (sig_str or "").strip()

    # hex (ללא רגישות לאותיות)
    if hmac.compare_digest(supplied.lower(), expected_hex):
        return True, "ok(hex)"

    # base64url: נשווה אחרי הסרת padding
    if hmac.compare_digest(supplied.rstrip("="), expected_b64):
        return True, "ok(b64url)"

    return False, "bad signature"



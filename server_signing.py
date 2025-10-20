# server_signing.py
import base64, hmac, hashlib, os, time
from typing import Tuple

def _load_key(env_name="API_SIGNING_SECRET") -> bytes:
    raw = os.environ.get(env_name, "")
    if not raw:
        raise RuntimeError(f"{env_name} not set")
    # מאשרים גם hex וגם ascii
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return raw.encode()

def _parse_exp(exp_str: str) -> int:
    exp = int(exp_str)
    # תמיכה במילישניות: 13 ספרות ומעלה
    if exp > 10**12:
        exp //= 1000
    return exp

def _constant_time_hex(h: hmac.HMAC) -> str:
    return h.hexdigest()

def _constant_time_b64(h: hmac.HMAC) -> str:
    dig = h.digest()
    return base64.urlsafe_b64encode(dig).decode().rstrip("=")

def verify_signature(ticket_id: str, exp_str: str, sig_str: str) -> Tuple[bool, str]:
    key = _load_key()
    exp = _parse_exp(exp_str)
    now = int(time.time())
    # תוקף
    if exp < now - 10:   # מרווח שלילי קטן נגד שעון מוזר
        return False, "expired"
    if exp > now + 600:  # 10 דקות קדימה לכל היותר
        return False, "exp too far in future"
    msg = f"{ticket_id}:{exp}".encode()
    mac = hmac.new(key, msg, hashlib.sha256)

    # בודקים גם hex וגם b64url
    expected_hex  = _constant_time_hex(mac)
    if hmac.compare_digest(sig_str, expected_hex):
        return True, "ok(hex)"

    expected_b64  = _constant_time_b64(hmac.new(key, msg, hashlib.sha256))
    if hmac.compare_digest(sig_str, expected_b64):
        return True, "ok(b64url)"

    return False, "bad signature"

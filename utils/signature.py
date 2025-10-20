# utils/signature.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, hmac, hashlib, time

OPS_SIGN_SECRET = (os.getenv("OPS_SIGN_SECRET") or "").encode()
ANTI_REPLAY_SKEW_SEC = int(os.getenv("ANTI_REPLAY_SKEW_SEC", "60"))

def sign_message(message: bytes) -> str:
    if not OPS_SIGN_SECRET:
        return ""
    return hmac.new(OPS_SIGN_SECRET, message, hashlib.sha256).hexdigest()

def verify_signed(ts: str, body: bytes, sig_hex: str) -> bool:
    """
    חתימה על: f"{ts}.{sha256(body)}"
    """
    if not OPS_SIGN_SECRET:
        return False
    try:
        ts_i = int(ts)
        if abs(int(time.time()) - ts_i) > max(5, ANTI_REPLAY_SKEW_SEC):
            return False
        body_hash = hashlib.sha256(body).hexdigest()
        msg = f"{ts}.{body_hash}".encode()
        exp = hmac.new(OPS_SIGN_SECRET, msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(exp, sig_hex.lower())
    except Exception:
        return False

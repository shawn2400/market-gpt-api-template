# security/hmac_verify.py
from __future__ import annotations
import os, hmac, hashlib, binascii, time, logging
from typing import Iterable, Optional, Tuple
from fastapi import Request

log = logging.getLogger("algogpt.security")

# ──────────────────────────────────────────────────────────────────────────────
# מקור הסוד: נעדיף את אותם שמות כמו בדיבאגר /alerts (_INGEST_) ואז תאימות
# ──────────────────────────────────────────────────────────────────────────────
def _get_secret_bytes(return_source: bool = False) -> Optional[Tuple[bytes, str, bool]] | Optional[bytes]:
    src = "none"
    s = os.getenv("ALERTS_INGEST_HMAC_SECRET")
    if s:
        src = "ALERTS_INGEST_HMAC_SECRET"
    else:
        s = os.getenv("WEBHOOK_HMAC_SECRET")
        if s:
            src = "WEBHOOK_HMAC_SECRET"
        else:
            s = os.getenv("OPS_SIGN_SECRET")
            if s:
                src = "OPS_SIGN_SECRET"

    if not s:
        return (None if return_source else None)

    key_is_hex = os.getenv("ALERTS_INGEST_HMAC_KEY_IS_HEX", "0").lower() in ("1","true","yes","on")
    if key_is_hex:
        try:
            b = binascii.unhexlify(s)
        except Exception:
            b = s.encode(); key_is_hex = False
    else:
        b = s.encode()

    if return_source:
        return b, src, key_is_hex
    return b

def _hmac_hex(k: bytes, msg: bytes) -> str:
    return hmac.new(k, msg, hashlib.sha256).hexdigest()

def _normalize_sig_header(sig: str) -> str:
    s = (sig or "").strip()
    if "=" in s:
        algo, val = s.split("=", 1)
        if algo.lower() in ("sha256", "hmac-sha256"):
            return val.strip()
    return s

# ──────────────────────────────────────────────────────────────────────────────
# אימות HMAC לבקשה (תואם לדיבאגר: RAW body, אותם headers)
# ──────────────────────────────────────────────────────────────────────────────
async def verify_request_hmac(
    request: Request,
    *,
    sig_header_names: Iterable[str] = ("X-Webhook-Hmac", "X-Signature", "X-AlgoGPT-Signature", "X-Hub-Signature-256"),
    ts_header_names: Iterable[str] = ("X-Webhook-Ts", "X-Signature-Timestamp", "X-AlgoGPT-Timestamp"),
    max_skew_sec: int = 180,
) -> Tuple[bool, str]:
    key = _get_secret_bytes()
    if not key:
        return (False, "missing_secret")

    body = await request.body()

    # חתימה מהכותרות
    hdr_sig_raw = ""
    for name in sig_header_names:
        v = request.headers.get(name)
        if v:
            hdr_sig_raw = v
            break
    if not hdr_sig_raw:
        return (False, "missing_signature_header")

    hdr_sig = _normalize_sig_header(hdr_sig_raw)

    # timestamp (אופציונלי)
    ts_val: Optional[str] = None
    for name in ts_header_names:
        v = request.headers.get(name)
        if v:
            ts_val = v.strip()
            break

    # אם יש timestamp – בדוק סטייה
    if ts_val:
        try:
            ts_float = float(ts_val)
            skew = abs(time.time() - ts_float)
            if skew > max_skew_sec:
                return (False, f"timestamp_skew({int(skew)}s)")
        except Exception:
            return (False, "bad_timestamp")

    # בדיקות: RAW ואז RAW עם prefix ts.
    exp = _hmac_hex(key, body)
    if hmac.compare_digest(exp, hdr_sig):
        return (True, "ok")

    if ts_val:
        msg = (ts_val + ".").encode() + body
        exp2 = _hmac_hex(key, msg)
        if hmac.compare_digest(exp2, hdr_sig):
            return (True, "ok")

    return (False, "bad_signature")

# ──────────────────────────────────────────────────────────────────────────────
# Bearer fallback (כש-HMAC כבוי)
# ──────────────────────────────────────────────────────────────────────────────
_BEARER = os.getenv("ALERTS_BEARER", "").strip()
def verify_bearer(request: Request, *, token: Optional[str] = None) -> bool:
    tok = (token or _BEARER or "").strip()
    if not tok:
        return False
    auth = request.headers.get("Authorization", "") or request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return False
    got = auth.split(" ", 1)[1].strip()
    try:
        return hmac.compare_digest(got, tok)
    except Exception:
        return False

__all__ = ["verify_request_hmac", "verify_bearer"]



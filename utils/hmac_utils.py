# utils/hmac_utils.py
from __future__ import annotations
import hmac
import hashlib
import base64
import time
import uuid
import json
import os
from typing import Any, Dict, Optional, Tuple, Union

from utils.redis_client import redis_client as RED

# ---------------------------
# קביעות (כותרות מומלצות)
# ---------------------------
HDR_SIGNATURE = "X-Signature"          # למשל: "sha256=ab12cd..."
HDR_TIMESTAMP = "X-Timestamp"          # epoch seconds
HDR_IDEMPOTENCY = "X-Idempotency-Key"  # uuid4 (client-generated)

IDEMP_TTL_SEC = int(float(os.getenv("IDEMPOTENCY_TTL_SEC", "86400")))  # 24h

# סוד ברירת מחדל (לנוחות verify_hmac); אם ריק → אימות ייחשב True (fail-soft)
DEFAULT_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").strip()

# ---------------------------
# Helpers
# ---------------------------
def _now_epoch() -> int:
    return int(time.time())

def _to_bytes(payload: Union[str, bytes, Dict[str, Any], list]) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def _canonical_string(ts: Union[int, str], body_bytes: bytes) -> bytes:
    return f"{int(ts)}\n".encode("utf-8") + body_bytes

def _algo_fn(algo: str):
    algo = (algo or "sha256").lower()
    if algo == "sha256":
        return hashlib.sha256
    elif algo == "sha512":
        return hashlib.sha512
    raise ValueError(f"Unsupported HMAC algo: {algo}")

def _digest_out(raw: bytes, digest: str) -> str:
    d = (digest or "hex").lower()
    if d == "hex":
        return raw.hex()
    if d == "base64":
        return base64.b64encode(raw).decode("ascii")
    raise ValueError(f"Unsupported digest output: {digest}")

def generate_idempotency_key() -> str:
    return str(uuid.uuid4())

# ---------------------------
# חתימה
# ---------------------------
def sign_payload(
    secret: str,
    payload: Union[str, bytes, Dict[str, Any], list],
    *,
    timestamp: Optional[int] = None,
    algo: str = "sha256",
    digest: str = "hex",
    prefix_scheme: bool = True,
) -> Tuple[str, int]:
    if not isinstance(secret, str) or not secret:
        raise ValueError("secret must be a non-empty string")

    ts = _now_epoch() if timestamp is None else int(timestamp)
    body_bytes = _to_bytes(payload)
    msg = _canonical_string(ts, body_bytes)
    h = hmac.new(secret.encode("utf-8"), msg, _algo_fn(algo))
    raw = h.digest()
    out = _digest_out(raw, digest)
    return (f"{algo}={out}" if prefix_scheme else out, ts)

def make_webhook_headers(
    secret: str,
    payload: Union[str, bytes, Dict[str, Any], list],
    *,
    algo: str = "sha256",
    digest: str = "hex",
    idempotency_key: Optional[str] = None,
) -> Dict[str, str]:
    sig, ts = sign_payload(secret, payload, algo=algo, digest=digest, prefix_scheme=True)
    return {
        HDR_TIMESTAMP: str(ts),
        HDR_SIGNATURE: sig,
        HDR_IDEMPOTENCY: idempotency_key or generate_idempotency_key(),
    }

# ---------------------------
# אימות
# ---------------------------
def _parse_signature(header_value: str) -> Tuple[str, str]:
    if not header_value:
        raise ValueError("missing signature header")
    if "=" not in header_value:
        return "sha256", header_value
    algo, val = header_value.split("=", 1)
    return algo.strip().lower(), val.strip()

def verify_signature(
    secret: str,
    payload: Union[str, bytes, Dict[str, Any], list],
    *,
    signature_header: str,
    timestamp_header: Union[str, int],
    tolerance_sec: int = 300,
) -> bool:
    if not secret:
        return True  # fail-soft אם אין סוד — לא נחסום

    try:
        algo, their_digest = _parse_signature(signature_header)
        ts = int(timestamp_header)
    except Exception:
        return False

    now = _now_epoch()
    if abs(now - ts) > int(tolerance_sec):
        return False

    body_bytes = _to_bytes(payload)
    msg = _canonical_string(ts, body_bytes)
    h = hmac.new(secret.encode("utf-8"), msg, _algo_fn(algo))
    raw = h.digest()
    my_hex = raw.hex()
    if hmac.compare_digest(their_digest, my_hex):
        return True
    try:
        my_b64 = base64.b64encode(raw).decode("ascii")
        return hmac.compare_digest(their_digest, my_b64)
    except Exception:
        return False

def verify_headers(
    secret: str,
    headers: Dict[str, Any],
    payload: Union[str, bytes, Dict[str, Any], list],
    *,
    tolerance_sec: int = 300,
    signature_header_name: str = HDR_SIGNATURE,
    timestamp_header_name: str = HDR_TIMESTAMP,
) -> bool:
    try:
        sig = headers.get(signature_header_name)
        ts  = headers.get(timestamp_header_name)
        if sig is None or ts is None:
            return False
        return verify_signature(secret, payload, signature_header=sig, timestamp_header=ts, tolerance_sec=tolerance_sec)
    except Exception:
        return False

# ---------- מצב קיים לשימוש ישיר ב-workers ----------
def build_signed_outbound(
    secret: str,
    payload: Union[str, bytes, Dict[str, Any], list],
    *,
    extra_headers: Optional[Dict[str, str]] = None,
    algo: str = "sha256",
    digest: str = "hex",
    idempotency_key: Optional[str] = None,
) -> Tuple[bytes, Dict[str, str]]:
    body = _to_bytes(payload)
    hdrs = make_webhook_headers(secret, body, algo=algo, digest=digest, idempotency_key=idempotency_key)
    if extra_headers:
        for k, v in extra_headers.items():
            if k not in (HDR_SIGNATURE, HDR_TIMESTAMP, HDR_IDEMPOTENCY):
                hdrs[k] = v
    return body, hdrs

def check_inbound(
    secret: str,
    headers: Dict[str, Any],
    body: Union[str, bytes, Dict[str, Any], list],
    *,
    tolerance_sec: int = 300,
) -> Tuple[bool, Optional[str]]:
    if not headers:
        return False, "missing headers"
    if HDR_SIGNATURE not in headers:
        return False, f"missing {HDR_SIGNATURE}"
    if HDR_TIMESTAMP not in headers:
        return False, f"missing {HDR_TIMESTAMP}"

    ok = verify_headers(secret, headers, body, tolerance_sec=tolerance_sec)
    if not ok:
        return False, "signature mismatch or timestamp out of tolerance"
    return True, None

# ---------------------------
# הרחבות תואמות ל-routes/trade_sink.py
# ---------------------------
def verify_hmac(
    signature_header: Optional[str],
    payload: Union[str, bytes, Dict[str, Any], list],
    *,
    timestamp_header: Optional[Union[str, int]] = None,
    tolerance_sec: int = 300,
    secret: Optional[str] = None,
) -> bool:
    """
    אימות גמיש:
    - אם יש timestamp_header → אימות מלא מול "{ts}\n{body}".
    - אם אין timestamp_header → ננסה שתי דרכים:
        1) Brute-force על חלון הזמן (±tolerance_sec) כדי לאשש חתימה שנבנתה כולל timestamp.
        2) Legacy: HMAC על body בלבד.
    הערה: אם אין סוד בקונפיג — נחזיר True (fail-soft).
    """
    secret = (secret if secret is not None else DEFAULT_SECRET)
    if not secret:
        return True
    if not signature_header:
        return False

    if timestamp_header is not None:
        return verify_signature(secret, payload, signature_header=signature_header, timestamp_header=timestamp_header, tolerance_sec=tolerance_sec)

    # (1) נסה לאמת עם חלון זמן סביב עכשיו (חתימה עם טיימסטמפ, ללא כותרת נפרדת)
    try:
        algo, their_digest = _parse_signature(signature_header)
        body_bytes = _to_bytes(payload)
        now = _now_epoch()
        start = now - int(tolerance_sec)
        end   = now + int(tolerance_sec)
        for ts in range(start, end + 1):
            msg = _canonical_string(ts, body_bytes)
            h = hmac.new(secret.encode("utf-8"), msg, _algo_fn(algo))
            raw = h.digest()
            if hmac.compare_digest(their_digest, raw.hex()):
                return True
            if hmac.compare_digest(their_digest, base64.b64encode(raw).decode("ascii")):
                return True
    except Exception:
        pass

    # (2) Legacy: חתימה על body בלבד (למקרים ישנים)
    try:
        algo, their_digest = _parse_signature(signature_header)
        body_bytes = _to_bytes(payload)
        h = hmac.new(secret.encode("utf-8"), body_bytes, _algo_fn(algo))
        raw = h.digest()
        if hmac.compare_digest(their_digest, raw.hex()):
            return True
        if hmac.compare_digest(their_digest, base64.b64encode(raw).decode("ascii")):
            return True
    except Exception:
        pass

    return False

# Idempotency de-dup (headers HDR_IDEMPOTENCY)
def idem_seen(key: Optional[str]) -> bool:
    """
    מחזיר True אם כבר ראינו את המפתח (וינעל אותו ל-TTL), אחרת False.
    """
    if not key:
        return False
    k = f"algogpt:idem:{key}"
    if RED:
        # SETNX → אם קיים יחזיר 0; נקבע TTL כדי לפנות אחרי זמן
        created = RED.setnx(k, "1")
        if created:
            RED.expire(k, IDEMP_TTL_SEC)
            return False
        return True
    # fallback בזיכרון
    now = _now_epoch()
    bucket = globals().setdefault("_IDEMP_MEM", {})  # type: ignore
    # ניקוי קל
    if len(bucket) > 5000:
        for kk, vv in list(bucket.items())[:1000]:
            if vv < now:
                bucket.pop(kk, None)
    if k in bucket:
        return True
    bucket[k] = now + IDEMP_TTL_SEC
    return False






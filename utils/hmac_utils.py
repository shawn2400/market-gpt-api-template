# utils/hmac_utils.py
from __future__ import annotations
import hmac
import hashlib
import base64
import time
import uuid
import json
from typing import Any, Dict, Optional, Tuple, Union

try:
    from utils.redis_client import redis_client as RED
except Exception:
    RED = None

# ---------------------------
# קביעות (כותרות מומלצות)
# ---------------------------
HDR_SIGNATURE = "X-Signature"          # לדוגמה: "sha256=ab12cd..."
HDR_TIMESTAMP = "X-Timestamp"          # epoch seconds
HDR_IDEMPOTENCY = "X-Idempotency-Key"  # uuid4 (client-generated)

# ---------------------------
# Helpers
# ---------------------------
def _now_epoch() -> int:
    return int(time.time())

def _to_bytes(payload: Union[str, bytes, Dict[str, Any], list]) -> bytes:
    """
    ממיר payload ל-bytes:
      - bytes → כפי שהוא
      - str → UTF-8
      - dict/list → JSON קנוני (sorted keys, separators ללא רווחים, UTF-8)
    """
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    # dict / list / כל אובייקט serializable
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def _canonical_string(ts: Union[int, str], body_bytes: bytes) -> bytes:
    """
    מחרוזת קנונית לחתימה:
        "{timestamp}\n{body}"
    """
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
    """ יוצר מפתח איסור כפילות (idempotency key) בצד השולח. """
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
    """
    מחזיר (signature_string, timestamp_used).
    signature_string כבר בפורמט:
        "sha256=<hex>" אם prefix_scheme=True
        אחרת רק ה־digest עצמו (hex/base64).
    """
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
    """
    יוצר כותרות לשיגור Webhook מאובטח:
      - X-Timestamp
      - X-Signature
      - X-Idempotency-Key (אם לא סופק — יווצר אוטומטית)
    """
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
    """
    מפרק "sha256=abcd..." ל-(algo, digest_str).
    אם לא קיים "=", מניח שזה digest ללא prefix ומחזיר ("sha256", value).
    """
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
    """
    מאמת חתימה נכנסת מול סוד משותף.
    - signature_header: ערך מלא של X-Signature (למשל "sha256=ab12...")
    - timestamp_header: ערך X-Timestamp (epoch seconds)
    - tolerance_sec: חלון סטייה (דיפולט 5 דקות)
    """
    if not secret:
        return False

    try:
        algo, their_digest = _parse_signature(signature_header)
        ts = int(timestamp_header)
    except Exception:
        return False

    # בדיקת חלון זמן
    now = _now_epoch()
    if abs(now - ts) > int(tolerance_sec):
        return False

    # חישוב חתימה מקומית
    body_bytes = _to_bytes(payload)
    msg = _canonical_string(ts, body_bytes)
    h = hmac.new(secret.encode("utf-8"), msg, _algo_fn(algo))
    my_hex = h.hexdigest()

    # תומך גם ב-base64 מהשולח (אם בחרו בפלט אחר):
    ok = hmac.compare_digest(their_digest, my_hex)
    if not ok:
        try:
            my_b64 = base64.b64encode(h.digest()).decode("ascii")
            ok = hmac.compare_digest(their_digest, my_b64)
        except Exception:
            pass
    return ok

def verify_headers(
    secret: str,
    headers: Dict[str, Any],
    payload: Union[str, bytes, Dict[str, Any], list],
    *,
    tolerance_sec: int = 300,
    signature_header_name: str = HDR_SIGNATURE,
    timestamp_header_name: str = HDR_TIMESTAMP,
) -> bool:
    """ אימות בעזרת מילון כותרות מלא. """
    try:
        sig = headers.get(signature_header_name)
        ts  = headers.get(timestamp_header_name)
        if sig is None or ts is None:
            return False
        return verify_signature(secret, payload, signature_header=sig, timestamp_header=ts, tolerance_sec=tolerance_sec)
    except Exception:
        return False

# ---- Aliases נוחים לשימוש ב־routes ----
_WEBHOOK_SECRET = (lambda: (import_os := __import__("os")).environ.get("WEBHOOK_HMAC_SECRET","").strip())()

def verify_hmac(signature_header: Optional[str], payload_bytes: bytes, timestamp_header: Optional[str] = None, tolerance_sec: int = 300) -> bool:
    """
    עטיפה נוחה ל־routes: מחייבת גם X-Timestamp.
    """
    if not signature_header or not timestamp_header:
        return False
    return verify_signature(_WEBHOOK_SECRET, payload_bytes, signature_header=signature_header, timestamp_header=timestamp_header, tolerance_sec=tolerance_sec)

# ---------------------------
# Idempotency
# ---------------------------
_IDEM_PREFIX = "algogpt:idem:"
# זיכרון בתהליך למקרה שאין Redis (עם ניקוי TTL גס)
_IDEM_LOCAL: Dict[str, int] = {}
_IDEM_DEFAULT_TTL = int((__import__("os").environ.get("IDEMPOTENCY_TTL_SEC") or "86400"))

def idem_seen(key: str, ttl_sec: Optional[int] = None) -> bool:
    """
    True אם כבר נראה (ואז לא מכניס שוב),
    False אם חדש (ובמקרה זה מסמן אותו כ־seen).
    """
    if not key:
        return False
    ttl = int(ttl_sec or _IDEM_DEFAULT_TTL)
    now = _now_epoch()

    # Redis עדיף
    if RED:
        try:
            full = _IDEM_PREFIX + key
            if RED.get(full):
                return True
            # NX + EX
            RED.set(full, "1", ex=ttl, nx=True)
            return False
        except Exception:
            pass

    # In-process fallback
    # ניקוי עצלני
    try:
        for k, exp in list(_IDEM_LOCAL.items()):
            if exp < now:
                _IDEM_LOCAL.pop(k, None)
    except Exception:
        pass

    if key in _IDEM_LOCAL and _IDEM_LOCAL.get(key, 0) >= now:
        return True
    _IDEM_LOCAL[key] = now + ttl
    return False

# ---------------------------
# Utilities לשני הכיוונים
# ---------------------------
def build_signed_outbound(
    secret: str,
    payload: Union[str, bytes, Dict[str, Any], list],
    *,
    extra_headers: Optional[Dict[str, str]] = None,
    algo: str = "sha256",
    digest: str = "hex",
    idempotency_key: Optional[str] = None,
) -> Tuple[bytes, Dict[str, str]]:
    """
    מחזיר (body_bytes, headers) למשלוח HTTP Outbound חתום.
    שימושי ל־httpx/requests.
    """
    body = _to_bytes(payload)
    hdrs = make_webhook_headers(secret, body, algo=algo, digest=digest, idempotency_key=idempotency_key)
    if extra_headers:
        # לא נדרוס את כותרות ה-HMAC
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
    """
    בדיקת בקשה נכנסת. מחזיר (ok, reason_if_not_ok)
    """
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




# utils/security.py
from __future__ import annotations
import hmac, hashlib, os, time, logging
from typing import Iterable, Optional, Tuple
from fastapi import Request

log = logging.getLogger("algogpt.security")

# ──────────────────────────────────────────────────────────────────────────────
# HMAC helpers
# ──────────────────────────────────────────────────────────────────────────────
_DEFAULT_SECRET = os.getenv("ALERTS_WEBHOOK_SECRET", "").strip()

def _normalize_sig_header(sig: str) -> str:
    """מקבל חתימה מ־Header—מחזיר ההקס בלבד (תומך בפורמט 'sha256=...')."""
    s = (sig or "").strip()
    if "=" in s:
        algo, val = s.split("=", 1)
        if algo.lower() in ("sha256", "hmac-sha256"):
            return val.strip()
    return s

def _hmac_sha256_hex(secret: str, data: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()

def _build_signing_payload(body: bytes, ts: Optional[str]) -> bytes:
    """
    אם מגיע timestamp header נחתום על 'ts.body' (מונע replay).
    אחרת – נחתום על body בלבד.
    """
    if ts:
        return (ts.encode("utf-8") + b"." + body)
    return body

async def verify_request_hmac(
    request: Request,
    *,
    secret: Optional[str] = None,
    sig_header_names: Iterable[str] = ("X-Signature", "X-Hub-Signature-256", "X-AlgoGPT-Signature"),
    ts_header_names: Iterable[str] = ("X-Signature-Timestamp", "X-AlgoGPT-Timestamp"),
    max_skew_sec: int = 180,
) -> Tuple[bool, str]:
    """
    אימות HMAC על בקשת FastAPI.
    - בודק מספר שמות Header אפשריים.
    - אם יש Timestamp – בודק חלון זמן (מונע replay).
    - מחזיר (ok, reason).
    """
    secret = (secret or _DEFAULT_SECRET or "").strip()
    if not secret:
        return (False, "missing_secret")

    # body as-is
    body = await request.body()

    # חתימה מהכותרות
    hdr_sig = None
    for name in sig_header_names:
        v = request.headers.get(name)
        if v:
            hdr_sig = _normalize_sig_header(v)
            break
    if not hdr_sig:
        return (False, "missing_signature_header")

    # timestamp (אופציונלי)
    ts_val: Optional[str] = None
    for name in ts_header_names:
        v = request.headers.get(name)
        if v:
            ts_val = v.strip()
            break

    # בדיקת skew אם יש timestamp
    if ts_val:
        try:
            ts_float = float(ts_val)
            skew = abs(time.time() - ts_float)
            if skew > max_skew_sec:
                return (False, f"timestamp_skew({int(skew)}s)")
        except Exception:
            return (False, "bad_timestamp")

    payload = _build_signing_payload(body, ts_val)
    expected = _hmac_sha256_hex(secret, payload)
    try:
        if not hmac.compare_digest(expected, hdr_sig):
            return (False, "bad_signature")
    except Exception:
        return (False, "compare_failed")
    return (True, "ok")

# ──────────────────────────────────────────────────────────────────────────────
# Bearer fallback (אם HMAC לא מופעל)
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






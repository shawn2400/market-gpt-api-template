# utils/security.py
from __future__ import annotations
import os, hmac, hashlib, base64, binascii, time, logging
from typing import Iterable, Optional, Tuple, Dict
from fastapi import Request

log = logging.getLogger("algogpt.security")

# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def _is_hex(s: str) -> bool:
    try:
        int(s, 16)
        return True
    except Exception:
        return False

def _lower_headers(h: Dict[str, str]) -> Dict[str, str]:
    return {k.lower(): v for k, v in h.items()}

def _pick_signature(headers_lower: Dict[str, str]) -> Tuple[Optional[str], str]:
    """
    מוצא חתימה מהכותרות הנפוצות ומחזיר: (signature, mode_hint)
    mode_hint ∈ {"hex","b64-or-unknown",""}.
    תומך ב:
      - X-Webhook-Hmac: <hex|b64>
      - X-Signature: <hex|b64>
      - X-AlgoGPT-Signature: <hex|b64>
      - X-Hub-Signature-256: sha256=<hex|b64>
    """
    cand = (
        headers_lower.get("x-webhook-hmac")
        or headers_lower.get("x-signature")
        or headers_lower.get("x-algogpt-signature")
    )
    if not cand:
        gh = headers_lower.get("x-hub-signature-256")
        if gh and gh.lower().startswith("sha256="):
            cand = gh.split("=", 1)[1].strip()

    if not cand:
        return None, ""

    c = cand.strip()
    if len(c) == 64 and _is_hex(c.lower()):
        return c.lower(), "hex"
    return c, "b64-or-unknown"

def _iter_secrets() -> list[Tuple[bytes, str]]:
    """
    מסיק מפתחות לבדיקה לפי ENV (בסדר עדיפויות):
      ALERTS_INGEST_HMAC_SECRET, WEBHOOK_HMAC_SECRET, ALERTS_HMAC_SECRET,
      OPS_SIGN_SECRET, ALERTS_WEBHOOK_SECRET, SECRET
    תומך בשדות *_KEY_IS_HEX=1 וגם בזיהוי HEX אוטומטי.
    מחזיר [(key_bytes, "NAME:hex|ascii"), ...]
    """
    names = [
        "ALERTS_INGEST_HMAC_SECRET",
        "WEBHOOK_HMAC_SECRET",
        "ALERTS_HMAC_SECRET",
        "OPS_SIGN_SECRET",
        "ALERTS_WEBHOOK_SECRET",
        "SECRET",
    ]
    out: list[Tuple[bytes, str]] = []
    for name in names:
        val = os.getenv(name, "")
        if not val:
            continue
        key_is_hex = os.getenv(f"{name}_KEY_IS_HEX", "").lower() in ("1", "true", "yes", "on")
        try_hex = key_is_hex or (len(val) % 2 == 0 and _is_hex(val.lower()))
        if try_hex:
            try:
                out.append((binascii.unhexlify(val), f"{name}:hex"))
                continue
            except Exception:
                pass
        out.append((val.encode("utf-8"), f"{name}:ascii"))
    return out

def _build_messages(raw: bytes, ts: Optional[str]) -> list[Tuple[bytes, str]]:
    """
    יוצר כל הווריאנטים האפשריים לחתימה:
      - raw
      - "<ts>." + raw  (אם קיים ts)
    מחזיר [(msg_bytes, tag), ...]
    """
    msgs = [(raw, "raw")]
    if ts:
        msgs.append(((ts + ".").encode() + raw, "ts.body"))
    return msgs

# ──────────────────────────────────────────────────────────────────────────────
# HMAC verification
# ──────────────────────────────────────────────────────────────────────────────

async def verify_request_hmac(
    request: Request,
    *,
    sig_header_names: Iterable[str] = (
        "X-Webhook-Hmac",
        "X-Signature",
        "X-AlgoGPT-Signature",
        "X-Hub-Signature-256",
    ),
    ts_header_names: Iterable[str] = (
        "X-Webhook-Ts",
        "X-Signature-Timestamp",
        "X-AlgoGPT-Timestamp",
    ),
    max_skew_sec: int = 300,
) -> Tuple[bool, str]:
    """
    אימות HMAC על בקשת FastAPI.
    """
    raw = await request.body()
    headers_lower = _lower_headers(request.headers)

    sig, mode_hint = _pick_signature(headers_lower)
    if not sig:
        return (False, "missing_signature")

    ts = None
    for name in ts_header_names:
        v = headers_lower.get(name.lower())
        if v:
            ts = v.strip()
            break
    if ts:
        try:
            tsf = float(ts)
            if abs(time.time() - tsf) > max_skew_sec:
                return (False, "timestamp_skew")
        except Exception:
            ts = None

    secrets = _iter_secrets()
    if not secrets:
        return (False, "missing_secret")

    messages = _build_messages(raw, ts)

    for key_bytes, key_label in secrets:
        for msg_bytes, msg_tag in messages:
            digest = hmac.new(key_bytes, msg_bytes, hashlib.sha256).digest()
            hex_sig = binascii.hexlify(digest).decode()
            b64_sig = base64.b64encode(digest).decode()

            if mode_hint == "hex":
                try:
                    if hmac.compare_digest(sig.lower(), hex_sig.lower()):
                        return (True, f"ok:{key_label}:{msg_tag}:hex")
                except Exception:
                    pass
            else:
                try:
                    if hmac.compare_digest(sig.lower(), hex_sig.lower()):
                        return (True, f"ok:{key_label}:{msg_tag}:hex")
                except Exception:
                    pass
                try:
                    if hmac.compare_digest(sig, b64_sig):
                        return (True, f"ok:{key_label}:{msg_tag}:b64")
                except Exception:
                    pass

    log.debug(
        "hmac_verify_failed: tried=%d secrets, msg_variants=%d, headers=%s",
        len(secrets), len(messages),
        {k: v for k, v in request.headers.items()
         if k.lower() in ("x-webhook-hmac","x-signature","x-hub-signature-256","x-webhook-ts","x-signature-timestamp","x-algogpt-timestamp")}
    )
    return (False, "bad_signature")

# ──────────────────────────────────────────────────────────────────────────────
# Bearer fallback (כש-HMAC לא חובה)
# ──────────────────────────────────────────────────────────────────────────────

def verify_bearer(request: Request, *, token: Optional[str] = None) -> bool:
    """
    בודק Bearer מול אחד מה־ENV הבאים:
      token (פרמטר), API_BEARER_TOKEN, API_TOKEN, ALERTS_BEARER
    """
    expected = (token or
                os.getenv("API_BEARER_TOKEN") or
                os.getenv("API_TOKEN") or
                os.getenv("ALERTS_BEARER") or "").strip()
    if not expected:
        return False

    auth = request.headers.get("Authorization") or request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return False

    got = auth.split(None, 1)[1].strip()
    try:
        return hmac.compare_digest(got, expected)
    except Exception:
        return False

# ──────────────────────────────────────────────────────────────────────────────
# תאימות לאחור: verify_hmac + idem_seen
# ──────────────────────────────────────────────────────────────────────────────

# verify_hmac – עטיפה לשם ישן שמודולים אחרים צפויים לייבא
async def verify_hmac(request: Request, **kwargs) -> Tuple[bool, str]:
    return await verify_request_hmac(request, **kwargs)

# idem_seen – אנטי-כפילות פשוט עם TTL בזיכרון
__IDEM_DB: Dict[str, float] = {}
def idem_seen(key: str, ttl_sec: int = 300) -> bool:
    """
    מחזיר True אם המפתח כבר נראה ועדיין בתוקף; אחרת שומר ומחזיר False.
    """
    now = time.time()
    # ניקוי פריטים שפג תוקפם (קליל)
    expired = [k for k, until in __IDEM_DB.items() if until <= now]
    for k in expired:
        __IDEM_DB.pop(k, None)

    until = __IDEM_DB.get(key)
    if until and until > now:
        return True
    __IDEM_DB[key] = now + max(1, int(ttl_sec))
    return False

__all__ = ["verify_request_hmac", "verify_bearer", "verify_hmac", "idem_seen"]




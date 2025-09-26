# security/hmac_verify.py
from __future__ import annotations
import base64
import binascii
import hashlib
import hmac
import json
import os
from typing import Dict, Optional, Tuple

# כותרות אפשריות לחתימה
HEADER_CANDIDATES = ("x-webhook-hmac", "x-hub-signature-256", "x-signature")

# סדר קדימויות ל-secrets מהסביבה
SECRET_CANDIDATES = (
    "ALERTS_INGEST_HMAC_SECRET",
    "ALERTS_HMAC_SECRET",
    "WEBHOOK_HMAC_SECRET",
    "OPS_SIGN_SECRET",
)

def _pick_header_sig(headers_lower: Dict[str, str]) -> Tuple[Optional[str], str]:
    """מאתר את החתימה מתוך אחת הכותרות הידועות. מחזיר (signature, header_name)."""
    for h in HEADER_CANDIDATES:
        if h in headers_lower:
            raw = headers_lower[h]
            # תמיכה ב-GitHub style: sha256=<hex>
            if raw.startswith("sha256="):
                raw = raw[7:]
            return raw, h
    return None, ""

def _decode_sig(sig: str) -> Tuple[Optional[bytes], str]:
    """מנסה לפענח את החתימה כ-hex, ואם נכשל — כ-base64."""
    try:
        return binascii.unhexlify(sig), "hex"
    except Exception:
        try:
            return base64.b64decode(sig), "base64"
        except Exception:
            return None, "unknown"

def _get_secret_bytes() -> Tuple[Optional[bytes], Dict[str, str]]:
    """
    בוחר secret ראשון שקיים לפי סדר קדימויות.
    אם מוגדר <NAME>_KEY_IS_HEX=1 (או ALERTS_HMAC_KEY_IS_HEX/HMAC_KEY_IS_HEX) — יבצע unhex.
    מחזיר (key_bytes, explain).
    """
    explain: Dict[str, str] = {}
    chosen_val: Optional[str] = None
    chosen_name: Optional[str] = None

    for name in SECRET_CANDIDATES:
        val = os.getenv(name)
        if val:
            chosen_val = val
            chosen_name = name
            break

    if not chosen_val or not chosen_name:
        explain["error"] = "missing_secret"
        explain["checked"] = ",".join(SECRET_CANDIDATES)
        return None, explain

    is_hex_flag = (
        os.getenv(f"{chosen_name}_KEY_IS_HEX")
        or os.getenv("ALERTS_HMAC_KEY_IS_HEX")
        or os.getenv("HMAC_KEY_IS_HEX")
        or "0"
    ).strip().lower() in ("1", "true", "yes", "on")

    try:
        key_bytes = (
            binascii.unhexlify(chosen_val) if is_hex_flag else chosen_val.encode("utf-8")
        )
    except binascii.Error as e:
        explain["error"] = "bad_hex_secret"
        explain["secret_name"] = chosen_name
        explain["detail"] = str(e)
        return None, explain

    explain["secret_name"] = chosen_name
    explain["key_is_hex"] = "1" if is_hex_flag else "0"
    return key_bytes, explain

def _canon_json(body: bytes) -> bytes:
    """מייצר JSON קנוני: בלי רווחים, מפתחות ממויינים."""
    obj = json.loads(body.decode("utf-8"))
    canon = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return canon

def verify_request(headers: Dict[str, str], body: bytes) -> Tuple[bool, Dict[str, str]]:
    """
    מוודא חתימת HMAC באחד משלושה אופנים:
      1) raw body
      2) canon-json (אם Content-Type הוא application/json)
      3) "<ts>.<body>" אם קיימת כותרת X-Webhook-Ts
    תומך ב-hex/base64 ובכותרות שונות.
    מחזיר (ok, explain_dict)
    """
    # ננרמל שמות כותרות ל-lower
    h = {k.lower(): v for k, v in headers.items()}
    explain: Dict[str, str] = {}

    # שליפת מפתח
    key, meta = _get_secret_bytes()
    explain.update(meta)
    if key is None:
        return False, explain

    # שליפת חתימה מהכותרות
    sig_str, hdr = _pick_header_sig(h)
    if not sig_str:
        explain["error"] = "missing_signature_header"
        explain["expected_headers"] = ",".join(HEADER_CANDIDATES)
        return False, explain

    sig_bytes, sig_fmt = _decode_sig(sig_str)
    if not sig_bytes:
        explain["error"] = "bad_signature_encoding"
        explain["sig_fmt"] = sig_fmt
        return False, explain

    explain["header_used"] = hdr
    explain["sig_fmt"] = sig_fmt

    # 1) raw
    digest_raw = hmac.new(key, body, hashlib.sha256).digest()
    if hmac.compare_digest(digest_raw, sig_bytes):
        explain["mode"] = "raw"
        return True, explain

    # 2) canon-json
    if h.get("content-type", "").lower().startswith("application/json"):
        try:
            c = _canon_json(body)
            digest_canon = hmac.new(key, c, hashlib.sha256).digest()
            if hmac.compare_digest(digest_canon, sig_bytes):
                explain["mode"] = "canon-json"
                return True, explain
        except Exception as e:
            explain["canon_err"] = str(e)

    # 3) ts.body
    ts = h.get("x-webhook-ts")
    if ts:
        msg = (ts + ".").encode("utf-8") + body
        digest_ts = hmac.new(key, msg, hashlib.sha256).digest()
        if hmac.compare_digest(digest_ts, sig_bytes):
            explain["mode"] = "ts.body"
            explain["ts"] = ts
            return True, explain

    explain["error"] = "no_mode_matched"
    return False, explain

# ---------- פונקציות נוחות לשימוש ב-Routes ----------

async def verify_request_hmac(request) -> Tuple[bool, str]:
    """
    API אסינכרוני לשימוש בראוטים:
    קורא את ה-body (ללא שינוי), מריץ verify_request ומחזיר (ok, reason_str).
    """
    body = await request.body()
    ok, info = verify_request(dict(request.headers), body)
    if ok:
        return True, info.get("mode", "ok")
    # reason קומפקטי אך אינפורמטיבי
    reason = (
        f"{info.get('error','?')}"
        f"; header={info.get('header_used','-')}"
        f"; fmt={info.get('sig_fmt','-')}"
        f"; secret={info.get('secret_name','-')}"
        f"; key_is_hex={info.get('key_is_hex','-')}"
    )
    if "canon_err" in info:
        reason += f"; canon_err={info['canon_err']}"
    if "expected_headers" in info:
        reason += f"; expected={info['expected_headers']}"
    return False, reason

def verify_bearer(request) -> bool:
    """
    אימות Bearer Token פשוט:
    בודק Authorization: Bearer <token> מול אחד מהערכים: API_BEARER_TOKEN / API_TOKEN / PRIMARY_API_TOKEN.
    """
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return False
    token = auth[7:].strip()

    expected = (
        os.getenv("API_BEARER_TOKEN")
        or os.getenv("API_TOKEN")
        or os.getenv("PRIMARY_API_TOKEN")
        or ""
    ).strip()

    return bool(expected) and token == expected


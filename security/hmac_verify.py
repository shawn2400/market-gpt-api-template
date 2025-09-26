# security/hmac_verify.py
import base64, binascii, hashlib, hmac, json, os
from typing import Optional, Tuple, Dict

HEADER_CANDIDATES = ("x-webhook-hmac", "x-hub-signature-256", "x-signature")
SECRET_CANDIDATES = (
    "ALERTS_INGEST_HMAC_SECRET",
    "ALERTS_HMAC_SECRET",
    "WEBHOOK_HMAC_SECRET",
    "OPS_SIGN_SECRET",
)

def _get_secret_and_flags(prefix: str = "") -> Tuple[Optional[bytes], Dict[str, str]]:
    """
    1) מוצא secret לפי סדר קדימות קבוע.
    2) אם יש <NAME>_KEY_IS_HEX=1 → יבצע unhex.
    3) מחזיר גם "explain" בשביל לוגים.
    """
    explain = {}
    chosen = None
    chosen_name = None
    for name in SECRET_CANDIDATES:
        if env := os.getenv(name):
            chosen = env
            chosen_name = name
            break
    if not chosen:
        return None, {"error": "missing_secret", "checked": ",".join(SECRET_CANDIDATES)}

    is_hex_flag = (
        os.getenv(f"{chosen_name}_KEY_IS_HEX")
        or os.getenv("ALERTS_HMAC_KEY_IS_HEX")
        or os.getenv("HMAC_KEY_IS_HEX")
        or "0"
    )
    try:
        key_bytes = (
            binascii.unhexlify(chosen)
            if is_hex_flag.strip() in ("1", "true", "TRUE")
            else chosen.encode()
        )
    except binascii.Error as e:
        return None, {"error": "bad_hex_secret", "name": chosen_name, "detail": str(e)}

    explain["secret_name"] = chosen_name
    explain["key_is_hex"] = "1" if key_bytes != chosen.encode() else "0"
    return key_bytes, explain

def _canon_json(body: bytes) -> bytes:
    obj = json.loads(body.decode("utf-8"))
    canon = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return canon

def _pick_header_sig(headers: Dict[str, str]) -> Tuple[Optional[str], str]:
    for h in HEADER_CANDIDATES:
        if h in headers:
            raw = headers[h]
            if raw.startswith("sha256="):
                raw = raw[7:]
            return raw, h
    return None, ""

def _decode_sig(sig: str) -> Tuple[Optional[bytes], str]:
    # נסה hex, ואם נכשל – נסה base64
    try:
        return binascii.unhexlify(sig), "hex"
    except Exception:
        try:
            return base64.b64decode(sig), "base64"
        except Exception:
            return None, "unknown"

def verify_request(headers: Dict[str, str], body: bytes) -> Tuple[bool, Dict[str, str]]:
    """
    מנסה כך:
    1) raw
    2) canon-json (אם Content-Type == application/json)
    3) ts.body (אם יש X-Webhook-Ts)
    מחזיר (ok, explain)
    """
    explain: Dict[str, str] = {}
    key, meta = _get_secret_and_flags()
    explain.update(meta)
    if key is None:
        return False, explain

    sig_str, hdr = _pick_header_sig({k.lower(): v for k, v in headers.items()})
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
    if headers.get("content-type", "").lower().startswith("application/json"):
        try:
            c = _canon_json(body)
            digest_canon = hmac.new(key, c, hashlib.sha256).digest()
            if hmac.compare_digest(digest_canon, sig_bytes):
                explain["mode"] = "canon-json"
                return True, explain
        except Exception as e:
            explain["canon_err"] = str(e)

    # 3) ts.body
    ts = headers.get("x-webhook-ts")
    if ts:
        msg = (ts + ".").encode() + body
        digest_ts = hmac.new(key, msg, hashlib.sha256).digest()
        if hmac.compare_digest(digest_ts, sig_bytes):
            explain["mode"] = "ts.body"
            explain["ts"] = ts
            return True, explain

    explain["error"] = "no_mode_matched"
    return False, explain

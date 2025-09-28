from __future__ import annotations
import os, hmac, hashlib, binascii, json, time
from typing import Optional, Dict, Any, Tuple, List

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["Public Feed"], include_in_schema=True)

# ---- helpers ----
def _env_truthy(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in ("1","true","yes","on")

def _load_secrets() -> List[Tuple[str, bytes, str]]:
    """
    מחזיר רשימת מפתחות זמינים לאימות:
    [(name, key_bytes, source), ...]
    """
    out: List[Tuple[str, bytes, str]] = []
    candidates = [
        ("ALERTS_INGEST_HMAC_SECRET", os.getenv("ALERTS_INGEST_HMAC_SECRET","")),
        ("WEBHOOK_HMAC_SECRET",       os.getenv("WEBHOOK_HMAC_SECRET","")),
        ("OPS_SIGN_SECRET",           os.getenv("OPS_SIGN_SECRET","")),
    ]
    key_is_hex_env = _env_truthy("ALERTS_INGEST_HMAC_KEY_IS_HEX", "0")

    for name, val in candidates:
        v = (val or "").strip()
        if not v:
            continue
        key_bytes: Optional[bytes] = None
        # אם הוגדר שהמפתח hex — נכבד. אחרת, ננסה לזהות אוטומטית 64 hex.
        if key_is_hex_env:
            try:
                key_bytes = binascii.unhexlify(v)
            except Exception:
                key_bytes = None
        if key_bytes is None:
            if len(v) == 64:
                try:
                    key_bytes = binascii.unhexlify(v)
                except Exception:
                    key_bytes = v.encode("utf-8")
            else:
                key_bytes = v.encode("utf-8")
        out.append((name, key_bytes, name))
    return out

def _extract_client_sig(request: Request) -> Tuple[Optional[str], str]:
    """
    שולף את החתימה מהלקוח מכמה מקומות נפוצים:
    - X-Webhook-Hmac: <hex>
    - X-Hub-Signature-256: sha256=<hex>
    - X-Signature: <hex>
    - query param: ?sig=<hex>
    מחזיר: (hex | None, מקור)
    """
    # 1) X-Webhook-Hmac
    sig = request.headers.get("x-webhook-hmac") or request.headers.get("X-Webhook-Hmac")
    if sig:
        return sig.strip(), "header:X-Webhook-Hmac"

    # 2) X-Hub-Signature-256: sha256=...
    sig2 = request.headers.get("x-hub-signature-256") or request.headers.get("X-Hub-Signature-256")
    if sig2:
        s = sig2.strip()
        if s.lower().startswith("sha256="):
            s = s.split("=", 1)[1]
        return s, "header:X-Hub-Signature-256"

    # 3) X-Signature
    sig3 = request.headers.get("x-signature") or request.headers.get("X-Signature")
    if sig3:
        return sig3.strip(), "header:X-Signature"

    # 4) query ?sig=
    qs = request.query_params.get("sig")
    if qs:
        return qs.strip(), "query:sig"

    return None, "missing"

def _calc_sha256_hex(key: bytes, raw: bytes, ts: Optional[str]) -> str:
    """
    אם יש ts — נחשב על b"{ts}.{raw}", אחרת על raw בלבד.
    """
    data = raw
    if ts is not None and ts != "":
        data = f"{ts}.".encode("utf-8") + raw
    return hmac.new(key, data, hashlib.sha256).hexdigest()

def _verify_hmac(raw: bytes, req: Request) -> Dict[str, Any]:
    """
    מאמת חתימת HMAC מול מספר מפתחות אפשריים.
    מחזיר אובייקט דיבוג עשיר. consumer יבדוק match==True.
    """
    provided_sig, sig_src = _extract_client_sig(req)
    ts_hdr = req.headers.get("x-webhook-ts") or req.headers.get("X-Webhook-Ts")

    secrets = _load_secrets()
    tried: List[Dict[str, Any]] = []
    match = False
    used = None

    for name, key, source in secrets:
        calc = _calc_sha256_hex(key, raw, ts_hdr)
        ok = provided_sig is not None and hmac.compare_digest(calc, provided_sig)
        tried.append({"key_name": name, "match": ok})
        if ok:
            match = True
            used = {"key_name": name, "source": source, "calc": calc}
            break

    return {
        "ok": match,
        "provided": provided_sig,
        "sig_source": sig_src,
        "ts_used": ts_hdr if ts_hdr is not None else None,
        "used_key": used,
        "tried": tried,
        "keys_count": len(secrets),
    }

# ---- routes ----

@router.get("/alerts/ping")
async def alerts_ping():
    return {"ok": True, "ping": "pong"}

@router.post("/alerts/_debug/alerts-hmac-check")
async def alerts_hmac_debug(request: Request):
    """
    דיבוג: מחשב בשרת את החתימה על raw body ומחזיר פירוט מלא.
    לא נועל על אימות — רק מחזיר תוצאות כדי שתוכל להשוות מול הצד שלך.
    """
    raw = await request.body()  # חשוב! לא json()
    info = _verify_hmac(raw, request)
    # הוסף hash מחושב גם ללא timestamp כדי לעזור דיאגנוסטית
    secrets = _load_secrets()
    calc_no_ts = [(_name, _calc_sha256_hex(k, raw, None)) for (_name, k, _src) in secrets]
    resp = {
        "ok": info["ok"],
        "provided": info["provided"],
        "sig_source": info["sig_source"],
        "ts_used": info["ts_used"],
        "tried": info["tried"],
        "calc_with_ts": info["used_key"]["calc"] if info["used_key"] else None,
        "calc_no_ts": [{"key_name": n, "sha256": h} for (n, h) in calc_no_ts],
        "keys_count": info["keys_count"],
    }
    # אל תחזיר מפתחות עצמם לעולם
    return JSONResponse(resp, status_code=200 if info["ok"] else 400)

@router.post("/alerts/ingest")
async def alerts_ingest(request: Request):
    """
    נקודת ingest אמיתית — נעילה על אימות HMAC.
    """
    raw = await request.body()
    if not raw:
        return JSONResponse({"ok": False, "error": "empty_body"}, status_code=400)

    info = _verify_hmac(raw, request)
    if not info["ok"]:
        return JSONResponse({"ok": False, "error": "Invalid HMAC signature"}, status_code=401)

    # כאן עיבוד התוכן (רצוי לעבוד מול raw -> json.loads())
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)

    # דוגמה של קבלה — שמור/טפל/דלג...
    accepted = True
    return {
        "ok": True,
        "accepted": accepted,
        "sig_source": info["sig_source"],
        "used_key": info["used_key"]["key_name"] if info["used_key"] else None,
    }

# אופציונלי: נקודות למסכי active/update אם יש לכם מימוש
@router.get("/alerts/trades/active")
async def alerts_active():
    return {"ok": True, "items": []}

@router.post("/alerts/trades/update")
async def alerts_update():
    return {"ok": True}























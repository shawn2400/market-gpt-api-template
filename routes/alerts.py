# routes/alerts.py
from __future__ import annotations
import os, hmac, hashlib, binascii, json
from typing import Optional, Tuple
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["alerts"])

# -------- helpers --------
def _load_secret() -> bytes:
    """
    נטען מפתח HMAC לפי סדר עדיפויות:
    ALERTS_INGEST_HMAC_SECRET | WEBHOOK_HMAC_SECRET | OPS_SIGN_SECRET
    אם ALERTS_INGEST_HMAC_KEY_IS_HEX=1 => מפוענח מ-hex, אחרת utf-8.
    """
    secret = (
        os.getenv("ALERTS_INGEST_HMAC_SECRET")
        or os.getenv("WEBHOOK_HMAC_SECRET")
        or os.getenv("OPS_SIGN_SECRET")
        or ""
    ).strip()
    if not secret:
        return b""
    is_hex = (os.getenv("ALERTS_INGEST_HMAC_KEY_IS_HEX","0").strip() in ("1","true","yes","on"))
    if is_hex:
        return binascii.unhexlify(secret)
    return secret.encode("utf-8")

def _calc(sig_key: bytes, payload: bytes) -> str:
    return hmac.new(sig_key, payload, hashlib.sha256).hexdigest()

def _calc_with_ts(sig_key: bytes, ts: str, payload: bytes) -> str:
    # פורמט: "<ts>." + raw
    return hmac.new(sig_key, (ts + ".").encode() + payload, hashlib.sha256).hexdigest()

def _normalize_sig(s: Optional[str]) -> Optional[str]:
    if not s: return None
    s = s.strip()
    if s.lower().startswith("sha256="):
        s = s.split("=",1)[1].strip()
    return s.lower()

def _extract_header_sig(req: Request) -> Tuple[Optional[str], Optional[str]]:
    # מחזיר: (sig_hex, ts) — ה-ts יכול להיות None
    h = req.headers
    sig = (
        h.get("x-webhook-hmac")
        or h.get("X-Webhook-Hmac")
        or h.get("x-hub-signature-256")
        or h.get("X-Hub-Signature-256")
        or ""
    )
    sig = _normalize_sig(sig)
    ts  = h.get("x-webhook-ts") or h.get("X-Webhook-Ts")
    return sig, ts

# -------- routes --------

@router.get("/alerts/ping")
async def alerts_ping():
    return {"ok": True, "role": "alerts", "hmac_required": (os.getenv("ALERTS_HMAC_REQUIRED","1").lower() in ("1","true","yes","on"))}

@router.post("/alerts/_debug/alerts-hmac-check")
async def alerts_hmac_check(request: Request):
    key = _load_secret()
    raw = await request.body()
    sig_hdr, ts_hdr = _extract_header_sig(request)

    if not key:
        return {"ok": False, "error": "missing_secret"}

    calc_no_ts = _calc(key, raw)
    res = {
        "ok": True,
        "calc_no_ts": calc_no_ts,
        "provided_sig": sig_hdr,
        "ts": ts_hdr,
    }
    if ts_hdr:
        res["calc_with_ts"] = _calc_with_ts(key, ts_hdr, raw)
    return res

@router.post("/alerts/ingest")
async def alerts_ingest(request: Request):
    """
    אימות HMAC:
      - אם קיים X-Webhook-Ts => נחשב "<ts>." + body
      - אחרת => נחשב על body בלבד
    חתימה מתקבלת כ:
      - X-Webhook-Hmac: <hex>
      - או  X-Hub-Signature-256: sha256=<hex>
    """
    key = _load_secret()
    if not key:
        return JSONResponse(status_code=401, content={"ok": False, "error": "HMAC secret not configured"})

    raw = await request.body()
    sig_hdr, ts_hdr = _extract_header_sig(request)
    if not sig_hdr:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Missing signature header"})

    expected = _calc_with_ts(key, ts_hdr, raw) if ts_hdr else _calc(key, raw)
    if not hmac.compare_digest(sig_hdr, expected):
        return JSONResponse(status_code=401, content={"ok": False, "error": "Invalid HMAC signature"})

    # אם עבר אימות — ננסה לפרסר לג׳ייסון (לא חובה)
    payload = None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        payload = {"raw_len": len(raw)}

    # כאן תוכל להמשיך ל-business logic / תור / DB
    return {"ok": True, "accepted": True, "ts": ts_hdr, "calc": expected, "payload": payload}

























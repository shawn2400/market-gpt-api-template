# routes/debug_hmac.py
from __future__ import annotations
import os, hmac, hashlib, base64
from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

router = APIRouter()

def _get_secret_bytes() -> bytes:
    s = os.getenv("WEBHOOK_HMAC_SECRET", "") or ""
    s = s.strip()
    if len(s) == 64:
        try:
            return bytes.fromhex(s)
        except Exception:
            pass
    return s.encode("utf-8")

def _clean_sig(v: str) -> str:
    v = (v or "").strip()
    if v.lower().startswith("sha256="):
        v = v.split("=", 1)[1].strip()
    return v

@router.post("/_debug/echo-hmac")
async def echo_hmac(request: Request):
    raw = await request.body()
    secret = _get_secret_bytes()
    hex_srv = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    b64_srv = base64.b64encode(hmac.new(secret, raw, hashlib.sha256).digest()).decode()

    # מה הגיע בכותרות
    hdrs = request.headers
    cand_names = ["x-webhook-hmac", "x-hub-signature-256", "x-signature"]
    got = {}
    for n in cand_names:
        v = hdrs.get(n, "")
        got[n] = v

    # ניקוי prefix sha256=
    got_clean = {n: _clean_sig(v) for n, v in got.items()}

    # האם יש התאמה כלשהי (hex/b64)
    match_hex = any(_clean_sig(v).lower() == hex_srv for v in got.values())
    match_b64 = any(_clean_sig(v) == b64_srv for v in got.values())

    # לא לחשוף סוד מלא בלוג/תגובה
    secret_hint = os.getenv("WEBHOOK_HMAC_SECRET", "")
    if len(secret_hint) > 10:
        secret_hint = secret_hint[:6] + "..." + secret_hint[-4:]

    return JSONResponse({
        "ok": True,
        "len_body": len(raw),
        "secret_hint": secret_hint,
        "server_hex": hex_srv,
        "server_b64": b64_srv,
        "headers_raw": got,
        "headers_clean": got_clean,
        "match_hex": match_hex,
        "match_b64": match_b64,
    })


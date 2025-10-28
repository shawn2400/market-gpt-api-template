# -*- coding: utf-8 -*-
from __future__ import annotations

import hmac, hashlib, time, json, re, os
from base64 import b64encode
from typing import Any, Dict, Optional, Tuple, List
from fastapi import APIRouter, Request, Body, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/debug", tags=["debug-signature"])

def _sha256_b64(data: bytes) -> str:
    return b64encode(hashlib.sha256(data).digest()).decode()

def _get_hmac_key_bytes() -> Optional[bytes]:
    cand = (
        os.getenv("API_SIGNING_SECRET")
        or os.getenv("OPS_SIGN_SECRET")
        or os.getenv("SIGNING_SECRET_HEX")
        or os.getenv("SECRET_HEX")
        or os.getenv("WEBHOOK_HMAC_SECRET")
        or ""
    ).strip()
    if not cand:
        return None
    try:
        if len(cand) == 64 and all(c in "0123456789abcdefABCDEF" for c in cand):
            return bytes.fromhex(cand)
    except Exception:
        pass
    return cand.encode("utf-8")

def _parse_signature_auth(h: str) -> Optional[Dict[str, Any]]:
    if not h or not h.lower().startswith("signature "):
        return None
    s = h[len("Signature "):].strip()
    parts: Dict[str, str] = {}
    for kv in re.split(r'\s*,\s*', s):
        if '="' not in kv:
            continue
        k, v = kv.split("=", 1)
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        parts[k.strip()] = v
    if not {"keyId","algorithm","headers","signature"}.issubset(parts):
        return None
    return {
        "keyId": parts["keyId"],
        "algorithm": parts["algorithm"].lower(),
        "headers": [x.strip().lower() for x in parts["headers"].split() if x.strip()],
        "signature": parts["signature"],
    }

def _build_sig_string(method: str, path: str, headers_lower: Dict[str, str], headers_order: List[str]) -> str:
    lines: List[str] = []
    for hname in headers_order:
        if hname == "(request-target)":
            lines.append(f"(request-target): {method.lower()} {path}")
        else:
            val = headers_lower.get(hname, "")
            lines.append(f"{hname}: {val}")
    return "\n".join(lines)

@router.post("/http-signature/verify")
async def debug_http_signature_verify(request: Request, payload: Dict[str, Any] = Body(default={})):
    raw = await request.body()
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    hdrs_lower = {k.lower(): v for k, v in request.headers.items()}
    parsed = _parse_signature_auth(auth)
    if not parsed:
        raise HTTPException(status_code=400, detail="missing_or_bad_authorization_signature")

    # body digest check (Digest or X-Content-SHA256)
    digest_ok = None
    digest_detail = None
    try:
        body_b64 = _sha256_b64(raw)
        if "digest" in hdrs_lower:
            try:
                scheme, b64v = (hdrs_lower["digest"] or "").split("=", 1)
                if scheme.strip().lower() != "sha-256":
                    digest_ok = False; digest_detail = "unsupported_digest_scheme"
                else:
                    digest_ok = (b64v.strip() == body_b64)
                    digest_detail = "ok" if digest_ok else "bad_digest"
            except Exception:
                digest_ok = False; digest_detail = "bad_digest_format"
        elif "x-content-sha256" in hdrs_lower:
            digest_ok = (hdrs_lower["x-content-sha256"].strip() == body_b64)
            digest_detail = "ok" if digest_ok else "bad_x_content_sha256"
        else:
            digest_ok = False; digest_detail = "missing_digest"
    except Exception as e:
        digest_ok = False; digest_detail = f"error:{e}"

    # signature base
    path = request.url.path
    sig_string = _build_sig_string(request.method, path, hdrs_lower, parsed["headers"])
    key = _get_hmac_key_bytes()
    if not key:
        raise HTTPException(status_code=503, detail="server_signing_secret_missing")
    calc = b64encode(hmac.new(key, sig_string.encode(), hashlib.sha256).digest()).decode()
    sig_ok = hmac.compare_digest(calc, parsed["signature"])

    # timestamp window (if provided)
    ts_detail = "skipped"
    ts_ok = True
    try:
        skew = int(os.getenv("SIG_TS_SKEW_SEC", "900") or 900)
        ts_raw = hdrs_lower.get("x-request-timestamp")
        if ts_raw is not None:
            ts_i = int(float(ts_raw))
            now_i = int(time.time())
            ts_ok = abs(now_i - ts_i) <= max(0, skew)
            ts_detail = "ok" if ts_ok else "timestamp_out_of_window"
    except Exception as e:
        ts_ok = False
        ts_detail = f"timestamp_bad_format:{e}"

    return JSONResponse({
        "ok": bool(sig_ok and ts_ok and digest_ok),
        "sig_ok": sig_ok,
        "calc_signature_b64": calc,
        "provided_signature_b64": parsed["signature"],
        "sig_string": sig_string,
        "headers_order": parsed["headers"],
        "digest_ok": digest_ok,
        "digest_detail": digest_detail,
        "timestamp_ok": ts_ok,
        "timestamp_detail": ts_detail,
    })



# clients/alerts_client.py
from __future__ import annotations
import os, hmac, hashlib, json
from typing import Any, Dict, Optional
import httpx

def _hmac_key_bytes() -> bytes:
    secret = os.environ.get("ALERTS_INGEST_HMAC_SECRET", "")
    if not secret:
        raise RuntimeError("ALERTS_INGEST_HMAC_SECRET is missing")
    if (os.environ.get("ALERTS_INGEST_HMAC_KEY_IS_HEX","0").lower() in ("1","true","yes","on")):
        return bytes.fromhex(secret)
    return secret.encode()

def _sign(body: bytes) -> str:
    key = _hmac_key_bytes()
    return hmac.new(key, body, hashlib.sha256).hexdigest()

def _headers(sig: Optional[str]) -> Dict[str,str]:
    h = {"Content-Type": "application/json"}
    if sig:
        h["x-webhook-hmac"] = sig
    else:
        # fallback אופציונלי
        api_key = os.environ.get("API_KEY") or os.environ.get("API_TOKEN") or os.environ.get("PRIMARY_API_TOKEN")
        if api_key:
            h["x-api-key"] = api_key
        bearer = os.environ.get("API_BEARER_TOKEN")
        if bearer:
            h["Authorization"] = f"Bearer {bearer}"
    return h

def _ingest_url() -> str:
    base = os.environ.get("ALERTS_INGEST_URL") or os.environ.get("PUBLIC_HOST") or os.environ.get("HOST") or ""
    if not base:
        raise RuntimeError("ALERTS_INGEST_URL / PUBLIC_HOST / HOST not set")
    return f"{base.rstrip('/')}/alerts/ingest"

# ----------------- SYNC -----------------
def post_ingest(payload: Dict[str, Any], use_hmac: bool = True) -> Dict[str, Any]:
    url = _ingest_url()
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = _sign(body) if use_hmac else None
    headers = _headers(sig)
    with httpx.Client(timeout=10.0) as cli:
        r = cli.post(url, content=body, headers=headers)
        r.raise_for_status()
        return r.json()

# ----------------- ASYNC -----------------
async def apost_ingest(payload: Dict[str, Any], use_hmac: bool = True) -> Dict[str, Any]:
    url = _ingest_url()
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = _sign(body) if use_hmac else None
    headers = _headers(sig)
    async with httpx.AsyncClient(timeout=10.0) as cli:
        r = await cli.post(url, content=body, headers=headers)
        r.raise_for_status()
        return r.json()

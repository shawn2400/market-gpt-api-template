import os, time, hmac, hashlib, json, secrets
from typing import Any, Dict, Optional
import httpx

def _is_hex64(s: str) -> bool:
    return len(s) == 64 and all(c in "0123456789abcdefABCDEF" for c in s)

def _sign_hex(secret: str, timestamp: str, nonce: str, body: bytes) -> str:
    key = bytes.fromhex(secret) if _is_hex64(secret) else secret.encode("utf-8")
    msg = f"{timestamp}.{nonce}.".encode("utf-8") + body
    return hmac.new(key, msg, hashlib.sha256).hexdigest()

async def approve_signed(ticket: Dict[str, Any],
                         host: Optional[str] = None,
                         secret: Optional[str] = None,
                         timeout: float = 15.0) -> Any:
    """
    שולח אישור חתום אל /ops/approve/signed בשירות הראשי (AlgoGPT).
    נדרש:
      - PUBLIC_HOST או host= (למשל https://algogpt-docker.onrender.com)
      - OPS_SIGN_SECRET או WEBHOOK_HMAC_SECRET
    """
    host = (host or os.getenv("PUBLIC_HOST") or "").rstrip("/")
    if not host:
        raise RuntimeError("Missing host (set PUBLIC_HOST or pass host=)")
    secret = secret or os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET")
    if not secret:
        raise RuntimeError("Missing secret (set OPS_SIGN_SECRET or WEBHOOK_HMAC_SECRET)")

    url = f"{host}/ops/approve/signed"
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    body = json.dumps(ticket, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sig = _sign_hex(secret, ts, nonce, body)

    headers = {
        "Content-Type": "application/json",
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "X-Signature": sig,
    }

    async with httpx.AsyncClient(timeout=timeout) as cli:
        r = await cli.post(url, content=body, headers=headers)
        text = r.text
        try:
            data = r.json()
        except Exception:
            data = None

        if r.status_code == 409:
            raise RuntimeError("Replay detected (nonce reuse).")
        if r.status_code == 401:
            raise RuntimeError("Signature rejected (secret/timestamp/body).")
        if r.status_code == 400:
            raise RuntimeError(f"Bad request: {text}")
        if r.status_code >= 500:
            raise RuntimeError(f"Server error {r.status_code}: {text}")
        if not r.is_success:
            raise RuntimeError(f"HTTP {r.status_code}: {text}")

        return data if data is not None else text

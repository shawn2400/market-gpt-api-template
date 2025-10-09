# approve_signed.py
import os, time, hmac, hashlib, json, secrets, httpx

HOST = os.getenv("PUBLIC_HOST", "https://algogpt-docker.onrender.com")
HMAC_SECRET = os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET")  # חובה

def sign_hex(secret: str, timestamp: str, nonce: str, body: bytes) -> str:
    # המפתח יכול להיות hex (64 תווים) או טקסט
    key = bytes.fromhex(secret) if len(secret) == 64 and all(c in "0123456789abcdefABCDEF" for c in secret) else secret.encode("utf-8")
    msg = f"{timestamp}.{nonce}.".encode("utf-8") + body
    return hmac.new(key, msg, hashlib.sha256).hexdigest()

async def approve_signed(ticket: dict, timeout=15.0):
    if not HMAC_SECRET:
        raise RuntimeError("Missing OPS_SIGN_SECRET/WEBHOOK_HMAC_SECRET")
    url = f"{HOST}/ops/approve/signed"
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    body = json.dumps(ticket, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sig = sign_hex(HMAC_SECRET, ts, nonce, body)

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
            raise RuntimeError("Replay detected (nonce reuse). Generate a fresh nonce.")
        if r.status_code == 401:
            raise RuntimeError("Signature rejected (bad secret / timestamp skew / body mismatch).")
        if r.status_code == 400:
            raise RuntimeError(f"Bad request: {text}")
        if r.status_code >= 500:
            raise RuntimeError(f"Server error {r.status_code}: {text}")
        if not r.is_success:
            raise RuntimeError(f"HTTP {r.status_code}: {text}")

        return data if data is not None else text

# דוגמה לשימוש
if __name__ == "__main__":
    import asyncio
    sample = {
        "ticket_id": "T_demo_py_001",
        "symbol": "ETHUSDT",
        "side": "BUY",
        "qty": 0,
        "leverage": 7,
        "tp1": 1.8, "tp2": 3.2, "tp3": 5.5,
        "sl": 1.2,
        "tp_splits": [0.4, 0.35, 0.25],
        "note": "[mode: AUTO] issued by py",
    }
    print(asyncio.run(approve_signed(sample)))

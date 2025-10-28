#!/usr/bin/env python3
# alerts_update.py
from __future__ import annotations
import os, hmac, hashlib, json, time, uuid, http.client, sys
from urllib.parse import urlparse

# ====== CONFIG ======
BASE_URL         = os.getenv("BASE_URL", os.getenv("PUBLIC_HOST", "https://algogpt-prod.onrender.com")).rstrip("/")
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN")  # חובה אם ההגנה מופעלת
OPS_SIGN_SECRET  = os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET")  # חובה
UPDATE_PATH      = os.getenv("UPDATE_PATH", "/alerts/trades/update")
TICKET_ID        = os.getenv("TICKET_ID", "T_demo_py_001")

if not API_BEARER_TOKEN:
    print("Missing API_BEARER_TOKEN", file=sys.stderr); sys.exit(2)
if not OPS_SIGN_SECRET:
    print("Missing OPS_SIGN_SECRET/WEBHOOK_HMAC_SECRET", file=sys.stderr); sys.exit(2)

# ====== BODY ======
body_dict = {"ticket_id": TICKET_ID, "action": "approve"}
body_str  = json.dumps(body_dict, separators=(",", ":"), ensure_ascii=False)
body_bytes = body_str.encode("utf-8")

# ====== signature base (ts|nonce\\nbody) -> hex ======
ts    = str(int(time.time()))
nonce = uuid.uuid4().hex

secret = OPS_SIGN_SECRET
try:
    key = (bytes.fromhex(secret) if (len(secret) == 64 and all(c in "0123456789abcdefABCDEF" for c in secret))
           else secret.encode("utf-8"))
except Exception:
    key = secret.encode("utf-8")

base = f"{ts}|{nonce}\n{body_str}"
sig_hex = hmac.new(key, base.encode("utf-8"), hashlib.sha256).hexdigest()

# ====== send ======
parsed = urlparse(BASE_URL)
if not parsed.scheme or not parsed.netloc:
    print("BASE_URL must include scheme and host, e.g. https://your-host", file=sys.stderr)
    sys.exit(2)

host = parsed.netloc
conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
conn = conn_cls(host, timeout=20)

headers = {
    "Authorization": f"Bearer {API_BEARER_TOKEN}",
    "Content-Type": "application/json",
    "X-Request-Timestamp": ts,
    "X-Request-Nonce": nonce,
    "X-Signature-Hex": sig_hex,
}

try:
    conn.request("POST", UPDATE_PATH, body=body_bytes, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    print("STATUS:", resp.status)
    for k, v in resp.getheaders():
        print(f"{k}: {v}")
    print()
    print(data.decode("utf-8", errors="replace"))
    if resp.status >= 400:
        sys.exit(1)
finally:
    conn.close()

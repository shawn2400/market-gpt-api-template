#!/usr/bin/env python3
# approve_signed.py
from __future__ import annotations
import os, hmac, hashlib, base64, json, time, secrets, http.client, sys
from urllib.parse import urlparse

# ====== CONFIG (env-first) ======
BASE_URL        = os.getenv("BASE_URL", os.getenv("PUBLIC_HOST", "https://algogpt-prod.onrender.com")).rstrip("/")
OPS_SIGN_SECRET = os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET")  # חובה
APPROVE_PATH    = os.getenv("APPROVE_PATH", "/ops/approve/signed")                 # הנתיב אצלך
TICKET_ID       = os.getenv("TICKET_ID", "T_demo_py_001")

# ====== BODY ======
body_dict = {
    "approve": True,
    "ticket_id": TICKET_ID,
    # (אופציונלי) תוכל להעביר כאן גם שדות משלימים כמו note / tp_splits וכו', לפי השרת שלך
}
body_bytes = json.dumps(body_dict, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

if not OPS_SIGN_SECRET:
    print("Missing OPS_SIGN_SECRET/WEBHOOK_HMAC_SECRET", file=sys.stderr)
    sys.exit(2)

# ====== headers base ======
ts    = str(int(time.time()))
nonce = secrets.token_hex(16)  # >= 16 תווים

# sha256 digest of body (base64) with 'SHA-256=' prefix in the Digest header
digest_b64 = base64.b64encode(hashlib.sha256(body_bytes).digest()).decode("ascii")
content_type = "application/json"

# ====== signature string per server contract ======
# headers order must match exactly the 'headers=' list:
# (request-target) host content-type x-request-nonce x-request-timestamp digest
parsed = urlparse(BASE_URL)
if not parsed.scheme or not parsed.netloc:
    print("BASE_URL must include scheme and host, e.g. https://your-host", file=sys.stderr)
    sys.exit(2)

host = parsed.netloc
req_target = f"post {APPROVE_PATH}"
headers_list = "(request-target) host content-type x-request-nonce x-request-timestamp digest"
sig_string = "\n".join([
    f"(request-target): {req_target}",
    f"host: {host}",
    f"content-type: {content_type}",
    f"x-request-nonce: {nonce}",
    f"x-request-timestamp: {ts}",
    f"digest: SHA-256={digest_b64}",
])

# ====== HMAC-SHA256 over sig_string, key may be hex or utf-8 ======
secret = OPS_SIGN_SECRET
try:
    if len(secret) == 64 and all(c in "0123456789abcdefABCDEF" for c in secret):
        key = bytes.fromhex(secret)
    else:
        key = secret.encode("utf-8")
except Exception:
    key = secret.encode("utf-8")

signature_b64 = base64.b64encode(hmac.new(key, sig_string.encode("utf-8"), hashlib.sha256).digest()).decode("ascii")
auth_header = f'Signature keyId="ops",algorithm="hmac-sha256",headers="{headers_list}",signature="{signature_b64}"'

# ====== send ======
conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
conn = conn_cls(host, timeout=20)

headers = {
    "Content-Type": content_type,
    "Host": host,
    "X-Request-Nonce": nonce,
    "X-Request-Timestamp": ts,
    "Digest": f"SHA-256={digest_b64}",
    "Authorization": auth_header,
}

try:
    conn.request("POST", APPROVE_PATH, body=body_bytes, headers=headers)
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


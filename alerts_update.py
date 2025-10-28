#!/usr/bin/env python3
# alerts_update.py
from __future__ import annotations
import os, hmac, hashlib, json, time, uuid, http.client, sys
from urllib.parse import urlparse

# ====== CONFIG ======
BASE_URL         = os.getenv("BASE_URL", os.getenv("PUBLIC_HOST", "https://algogpt-prod.onrender.com")).rstrip("/")
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN")                 # חובה אם המסלול מוגן בבירר
OPS_SIGN_SECRET  = os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET")  # חובה
UPDATE_PATH      = os.getenv("UPDATE_PATH", "/alerts/trades/update")
TICKET_ID        = os.getenv("TICKET_ID", "T_demo_py_001")
ACTION           = os.getenv("ACTION", "approve").strip().lower()  # approve / reject / cancel / refresh
HTTP_TIMEOUT_SEC = int(os.getenv("HTTP_TIMEOUT", "20"))

# ולידציה מוקדמת
if not OPS_SIGN_SECRET:
    print("Missing OPS_SIGN_SECRET/WEBHOOK_HMAC_SECRET", file=sys.stderr)
    sys.exit(2)
if ACTION not in ("approve", "reject", "cancel", "refresh"):
    print(f"Invalid ACTION='{ACTION}' (allowed: approve/reject/cancel/refresh)", file=sys.stderr)
    sys.exit(2)

# ====== BODY ======
body_dict  = {"ticket_id": TICKET_ID, "action": ACTION}
body_str   = json.dumps(body_dict, separators=(",", ":"), ensure_ascii=False)
body_bytes = body_str.encode("utf-8")

# ====== signature base (ts|nonce\nbody) -> hex ======
ts    = str(int(time.time()))
nonce = uuid.uuid4().hex

secret = OPS_SIGN_SECRET
try:
    # תמיכה במפתח HEX-64 או טקסט
    key = bytes.fromhex(secret) if (len(secret) == 64 and all(c in "0123456789abcdefABCDEF" for c in secret)) else secret.encode("utf-8")
except Exception:
    key = secret.encode("utf-8")

base = f"{ts}|{nonce}\n{body_str}"
sig_hex = hmac.new(key, base.encode("utf-8"), hashlib.sha256).hexdigest()

# ====== send ======
parsed = urlparse(BASE_URL)
if not parsed.scheme or not parsed.netloc:
    print("BASE_URL must include scheme and host, e.g. https://your-host", file=sys.stderr)
    sys.exit(2)
if not UPDATE_PATH.startswith("/"):
    UPDATE_PATH = "/" + UPDATE_PATH

host = parsed.netloc
conn_cls = http.client.HTTPSConnection if parsed.scheme.lower() == "https" else http.client.HTTPConnection
conn = conn_cls(host, timeout=HTTP_TIMEOUT_SEC)

# נבנה כותרות — גם הסט ה”קלאסי“ וגם ה־fallback ששלחת קודם (לפי השרת שלך די באחד; הכנסת שניהם לא מזיקה)
headers = {
    "Content-Type": "application/json",

    # Bearer אם המסלול מוגן; אם אין — נמשיך ללא (ייתכן 401)
    **({"Authorization": f"Bearer {API_BEARER_TOKEN}"} if API_BEARER_TOKEN else {}),

    # סט שמות הראשים “הקלאסי” ששימושי בשרת:
    "X-Timestamp": ts,
    "X-Nonce": nonce,
    "X-Signature": sig_hex,

    # סט fallback תואם לניסויים הקודמים שלך:
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
    print(data.decode("utf-8", errors="replace") or "<no body>")
    if resp.status >= 400:
        sys.exit(1)
finally:
    conn.close()


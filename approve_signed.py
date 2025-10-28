#!/usr/bin/env python3
# approve_signed.py  —  Production-grade client for /ops/approve/signed
from __future__ import annotations
import os, hmac, hashlib, base64, json, time, secrets, http.client, sys, argparse
from urllib.parse import urlparse

def _b64_sha256(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")

def _key_from_secret(secret: str) -> bytes:
    # HEX (64 nibbles) or UTF-8 text
    try:
        if len(secret) == 64 and all(c in "0123456789abcdefABCDEF" for c in secret):
            return bytes.fromhex(secret)
    except Exception:
        pass
    return secret.encode("utf-8")

def build_sig_string(host: str, path: str, content_type: str, nonce: str, ts: str, digest_b64: str) -> str:
    # MUST match headers list exactly:
    # (request-target) host content-type x-request-nonce x-request-timestamp digest
    req_target = f"post {path}"
    return "\n".join([
        f"(request-target): {req_target}",
        f"host: {host}",
        f"content-type: {content_type}",
        f"x-request-nonce: {nonce}",
        f"x-request-timestamp: {ts}",
        f"digest: SHA-256={digest_b64}",
    ])

def sign(sig_string: str, secret: str) -> str:
    key = _key_from_secret(secret)
    mac = hmac.new(key, sig_string.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(mac).decode("ascii")

def do_request(
    base_url: str,
    path: str,
    body: dict,
    ops_sign_secret: str,
    api_bearer_token: str | None = None,
    timeout: int = 20,
    reject: bool = False,
) -> int:
    base_url = base_url.rstrip("/")
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        print("BASE_URL must include scheme and host, e.g. https://your-host", file=sys.stderr)
        return 2

    host = parsed.netloc
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        print("Unsupported scheme (use http or https)", file=sys.stderr)
        return 2

    content_type = "application/json"
    body_dict = dict(body)
    if reject:
        # If you want a reject path through the same endpoint:
        body_dict["approve"] = False

    body_bytes = json.dumps(body_dict, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)  # >= 16 chars
    digest_b64 = _b64_sha256(body_bytes)

    sig_string = build_sig_string(host, path, content_type, nonce, ts, digest_b64)
    signature_b64 = sign(sig_string, ops_sign_secret)
    headers_list = "(request-target) host content-type x-request-nonce x-request-timestamp digest"
    auth_header = f'Signature keyId="ops",algorithm="hmac-sha256",headers="{headers_list}",signature="{signature_b64}"'

    conn_cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(host, timeout=timeout)

    headers = {
        "Content-Type": content_type,
        "Host": host,
        "X-Request-Nonce": nonce,
        "X-Request-Timestamp": ts,
        "Digest": f"SHA-256={digest_b64}",
        "Authorization": auth_header,
    }
    if api_bearer_token:
        headers["X-Alt-Auth"] = f"Bearer {api_bearer_token}"  # אופציונלי; השרת יכול גם לבדוק אותו אם מוגדר
        # אם השרת מצפה ל־Authorization Bearer נוסף לצד Signature:
        # headers["Authorization-Alt"] = f"Bearer {api_bearer_token}"

    try:
        conn.request("POST", path, body=body_bytes, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        print("STATUS:", resp.status)
        for k, v in resp.getheaders():
            print(f"{k}: {v}")
        print()
        txt = data.decode("utf-8", errors="replace")
        print(txt if txt else "<no body>")
        return 0 if resp.status < 400 else 1
    finally:
        conn.close()

def main() -> int:
    p = argparse.ArgumentParser(description="Approve (or reject) a ticket using HMAC HTTP Signature.")
    p.add_argument("--base-url", default=os.getenv("BASE_URL", os.getenv("PUBLIC_HOST", "https://algogpt-prod.onrender.com")),
                   help="Service base URL (default from BASE_URL or PUBLIC_HOST)")
    p.add_argument("--path", default=os.getenv("APPROVE_PATH", "/ops/approve/signed"),
                   help="Approve endpoint path (default /ops/approve/signed)")
    p.add_argument("--ticket", default=os.getenv("TICKET_ID", "T_demo_py_001"), help="Ticket ID to approve/reject")
    p.add_argument("--secret", default=os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET"),
                   help="OPS_SIGN_SECRET (HEX(64) or UTF-8). REQUIRED")
    p.add_argument("--bearer", default=os.getenv("API_BEARER_TOKEN"), help="Optional API Bearer token")
    p.add_argument("--note", default=os.getenv("APPROVE_NOTE", ""),
                   help="Optional note to include in the request body")
    p.add_argument("--timeout", type=int, default=int(os.getenv("HTTP_TIMEOUT", "20")), help="HTTP timeout (sec)")
    p.add_argument("--reject", action="store_true", help="Send a reject (approve=false) instead of approve")
    p.add_argument("--dry-run", action="store_true", help="Print request then exit")
    args = p.parse_args()

    if not args.secret:
        print("Missing OPS_SIGN_SECRET / WEBHOOK_HMAC_SECRET (use --secret or set env var)", file=sys.stderr)
        return 2

    body = {
        "approve": True,
        "ticket_id": args.ticket,
    }
    if args.note:
        body["note"] = args.note

    if args.dry_run:
        # Show exactly what we will send (without revealing secret)
        preview = {
            "base_url": args.base_url,
            "path": args.path,
            "body": body | ({"approve": False} if args.reject else {}),
            "has_bearer": bool(args.bearer),
            "timeout": args.timeout,
        }
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    return do_request(
        base_url=args.base_url,
        path=args.path,
        body=body,
        ops_sign_secret=args.secret,
        api_bearer_token=args.bearer,
        timeout=args.timeout,
        reject=args.reject,
    )

if __name__ == "__main__":
    sys.exit(main())



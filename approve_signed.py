#!/usr/bin/env python3
# approve_signed.py  —  Production-grade client for /ops/approve/signed
from __future__ import annotations
import os, hmac, hashlib, base64, json, time, secrets, http.client, sys, argparse
from urllib.parse import urlparse

def _b64_sha256(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")

def _key_from_secret(secret: str) -> bytes:
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

def do_request(base_url: str, path: str, body: dict, ops_sign_secret: str,
               api_bearer_token: str | None = None, timeout: int = 20, reject: bool = False) -> int:
    base_url = base_url.rstrip("/")
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        print("BASE_URL must include scheme and host, e.g. https://your-host", file=sys.stderr)
        return 2
    host, scheme = parsed.netloc, parsed.scheme.lower()
    if scheme not in ("http","https"):
        print("Unsupported scheme", file=sys.stderr); return 2

    content_type = "application/json"
    body_dict = dict(body)
    if reject: body_dict["approve"] = False
    body_bytes = json.dumps(body_dict, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)
    digest_b64 = _b64_sha256(body_bytes)

    sig_string = build_sig_string(host, path, content_type, nonce, ts, digest_b64)
    signature_b64 = sign(sig_string, ops_sign_secret)
    headers_list = "(request-target) host content-type x-request-nonce x-request-timestamp digest"
    sig_auth = f'Signature keyId="ops",algorithm="hmac-sha256",headers="{headers_list}",signature="{signature_b64}"'

    conn = (http.client.HTTPSConnection if scheme=="https" else http.client.HTTPConnection)(host, timeout=timeout)
    headers = {
        "Content-Type": content_type,
        "Host": host,
        "X-Request-Nonce": nonce,
        "X-Request-Timestamp": ts,
        "Digest": f"SHA-256={digest_b64}",
        "Authorization": sig_auth,
    }
    if api_bearer_token:
        headers["X-Alt-Auth"] = f"Bearer {api_bearer_token}"

    try:
        conn.request("POST", path, body=body_bytes, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        print("STATUS:", resp.status)
        for k,v in resp.getheaders(): print(f"{k}: {v}")
        print(); print(data.decode("utf-8","replace") or "<no body>")
        return 0 if resp.status < 400 else 1
    finally:
        conn.close()

def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=os.getenv("BASE_URL", os.getenv("PUBLIC_HOST","https://algogpt-prod.onrender.com")))
    p.add_argument("--path", default=os.getenv("APPROVE_PATH","/ops/approve/signed"))
    p.add_argument("--ticket", default=os.getenv("TICKET_ID","T_demo_py_001"))
    p.add_argument("--secret", default=os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET"))
    p.add_argument("--bearer", default=os.getenv("API_BEARER_TOKEN"))
    p.add_argument("--note", default=os.getenv("APPROVE_NOTE",""))
    p.add_argument("--timeout", type=int, default=int(os.getenv("HTTP_TIMEOUT","20")))
    p.add_argument("--reject", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if not args.secret:
        print("Missing OPS_SIGN_SECRET / WEBHOOK_HMAC_SECRET", file=sys.stderr); return 2
    body = {"approve": True, "ticket_id": args.ticket}
    if args.note: body["note"] = args.note
    if args.dry_run:
        print(json.dumps({"base_url":args.base_url,"path":args.path,"body":body,"reject":args.reject,"has_bearer":bool(args.bearer)}, ensure_ascii=False, indent=2))
        return 0
    return do_request(args.base_url, args.path, body, args.secret, args.bearer, args.timeout, args.reject)

if __name__ == "__main__":
    sys.exit(main())




#!/usr/bin/env python3
import argparse, hmac, hashlib, json, time, sys, os

def make_sig(secret: str, ts: str, body_bytes: bytes) -> str:
    msg = ts.encode("utf-8") + b"." + body_bytes
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()

def main():
    ap = argparse.ArgumentParser(description="Create HMAC signature for /ultra/ops/*")
    ap.add_argument("--secret", default=os.getenv("OPS_SIGN_SECRET", ""), help="OPS_SIGN_SECRET (or env)")
    ap.add_argument("--ts", help="timestamp string; default: now as int", default=None)
    ap.add_argument("--json", help="JSON body string (e.g. '{\"patch\": {\"TP_DYNAMIC_ENABLE\":1}}')", default="")
    ap.add_argument("--file", help="Read body from file instead of --json", default=None)
    args = ap.parse_args()

    if not args.secret:
        print("ERROR: missing --secret or OPS_SIGN_SECRET env", file=sys.stderr)
        sys.exit(2)

    if args.file:
        body = open(args.file, "rb").read()
    else:
        # normalize JSON pretty consistently
        if args.json.strip():
            obj = json.loads(args.json)
            body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        else:
            body = b""

    ts = args.ts if args.ts is not None else str(int(time.time()))
    sig = make_sig(args.secret, ts, body)

    # Output that can be used directly in curl
    print("X-Timestamp:", ts)
    print("X-Signature:", sig)
    if body:
        print("Body:", body.decode("utf-8"))

if __name__ == "__main__":
    main()

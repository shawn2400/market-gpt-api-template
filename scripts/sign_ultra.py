#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sign_ultra.py — כלי חתימת HMAC לבקשות /ultra/ops/*
שימושים:
  1) הדפסת חתימה בלבד:
       TS=1699999999 OPS_SIGN_SECRET='secret' BODY='{"patch":{"X":1}}' ./scripts/sign_ultra.py --print-sig

  2) שליחת בקשת POST חתומה (reload או prefs):
       OPS_SIGN_SECRET='secret' ./scripts/sign_ultra.py --base https://algogpt-docker.onrender.com --reload
       OPS_SIGN_SECRET='secret' ./scripts/sign_ultra.py --base https://algogpt-docker.onrender.com --prefs '{"patch":{"TP_DYNAMIC_ENABLE":1}}'

משתנים/דגלים:
  --base <URL>        בסיס השרת (ברירת מחדל: http://127.0.0.1:10000)
  --reload            לשלוח POST /ultra/ops/policy/reload (ללא גוף)
  --prefs '<JSON>'    לשלוח POST /ultra/ops/runtime/prefs עם גוף JSON
  --print-sig         הדפסת חתימה בלבד (ללא שליחה)
  --ts <EPOCH>        לציין טיימסטמפ ידני; אחרת נלקח מהשעה הנוכחית
ENV:
  OPS_SIGN_SECRET     (חובה לשליחה/חתימה)
  BODY                (אופציונלי, אם לא הועבר --prefs)
  TS                  (אופציונלי, אם לא הועבר --ts)
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from typing import Optional

try:
    import requests  # type: ignore
except Exception:
    requests = None


def make_sig(secret: str, ts: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), ts.encode("utf-8") + b"." + body, hashlib.sha256).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="AlgoGPT UltraTop HMAC signer / client")
    ap.add_argument("--base", default=os.environ.get("BASE_URL", "http://127.0.0.1:10000"))
    ap.add_argument("--reload", action="store_true")
    ap.add_argument("--prefs", default=None)
    ap.add_argument("--print-sig", dest="print_sig", action="store_true")  # <<< FIXED name
    ap.add_argument("--ts", default=os.environ.get("TS"))
    args = ap.parse_args()

    secret = os.environ.get("OPS_SIGN_SECRET", "")
    if not secret:
        print("OPS_SIGN_SECRET is required (export it)", file=sys.stderr)
        return 2

    # decide body
    body_str: Optional[str] = None
    if args.prefs is not None:
        body_str = args.prefs
    else:
        env_body = os.environ.get("BODY")
        body_str = env_body if env_body is not None else ""

    # TS
    ts = args.ts or str(int(time.time()))

    # bytes
    body_bytes = body_str.encode("utf-8")
    sig = make_sig(secret, ts, body_bytes)

    if args.print_sig:
        print(sig)
        return 0

    if requests is None:
        print("python-requests is required for HTTP send. pip install requests", file=sys.stderr)
        return 3

    if args.reload:
        url = f"{args.base.rstrip('/')}/ultra/ops/policy/reload"
        resp = requests.post(url, headers={"X-Timestamp": ts, "X-Signature": sig}, timeout=20)
        print(resp.status_code)
        try:
            print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
        except Exception:
            print(resp.text)
        return 0 if resp.ok else 1

    if args.prefs is not None or os.environ.get("BODY") is not None:
        url = f"{args.base.rstrip('/')}/ultra/ops/runtime/prefs"
        headers = {"X-Timestamp": ts, "X-Signature": sig, "Content-Type": "application/json"}
        resp = requests.post(url, headers=headers, data=body_bytes, timeout=25)
        print(resp.status_code)
        try:
            print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
        except Exception:
            print(resp.text)
        return 0 if resp.ok else 1

    print("Nothing to do. Use --reload or --prefs '<JSON>' or set BODY env.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())


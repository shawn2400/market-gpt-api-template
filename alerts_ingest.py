#!/usr/bin/env python3
# alerts_ingest.py — POST /alerts/ingest (Bearer only or with HMAC if מוגדר אצלך)
from __future__ import annotations
import os, json, http.client, sys, argparse
from urllib.parse import urlparse

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=os.getenv("BASE_URL","https://algogpt-prod.onrender.com"))
    p.add_argument("--path", default=os.getenv("ALERTS_INGEST_PATH","/alerts/ingest"))
    p.add_argument("--bearer", default=os.getenv("API_BEARER_TOKEN"))
    p.add_argument("--symbol", default="SOLUSDT")
    p.add_argument("--side", default="BUY")
    p.add_argument("--lev", type=int, default=10)
    p.add_argument("--budget-min", type=float, default=float(os.getenv("AUTO_BUDGET_MIN","100")))
    p.add_argument("--budget-max", type=float, default=float(os.getenv("AUTO_BUDGET_MAX","200")))
    p.add_argument("--tp1", type=float, default=0.0)
    p.add_argument("--tp2", type=float, default=0.0)
    p.add_argument("--sl", type=float, default=0.0)
    p.add_argument("--require-approval", action="store_true")
    args = p.parse_args()

    body = {
        "symbol": args.symbol,
        "side": args.side,
        "qty": 0,
        "leverage": args.lev,
        "tp1": args.tp1, "tp2": args.tp2, "sl": args.sl,
        "budget_min": args.budget_min, "budget_max": args.budget_max,
        "require_approval": bool(args.require_approval),
        "note": "[mode: HYBRID] signal via ingest tester",
    }
    u = urlparse(args.base_url.rstrip("/"))
    conn_cls = http.client.HTTPSConnection if u.scheme=="https" else http.client.HTTPConnection
    conn = conn_cls(u.netloc, timeout=20)
    headers = {"Content-Type":"application/json"}
    if args.bearer: headers["Authorization"] = f"Bearer {args.bearer}"
    try:
        conn.request("POST", args.path, body=json.dumps(body,separators=(",",":"),ensure_ascii=False).encode("utf-8"), headers=headers)
        r = conn.getresponse()
        d = r.read()
        print("STATUS:", r.status)
        for k,v in r.getheaders(): print(f"{k}: {v}")
        print(); print(d.decode("utf-8","replace") or "<no body>")
        return 0 if r.status < 400 else 1
    finally:
        conn.close()

if __name__ == "__main__":
    sys.exit(main())

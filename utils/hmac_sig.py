# utils/hmac_sig.py
from __future__ import annotations
import argparse, hmac, hashlib
from typing import Dict

def hmac_hex(secret: str, data: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()

def legacy(secret: str, ticket_id: str, action: str, expires: str) -> str:
    base = f"{ticket_id}|{action}|{expires}".encode("utf-8")
    return hmac_hex(secret, base)

def canonical(secret: str, params: Dict[str, str]) -> str:
    # חותמים בדיוק על k=v ממויין (ללא sig), במפתחות: action, by, expires, require, ticket_id, version
    allowed = {"action", "by", "expires", "require", "ticket_id", "version"}
    filtered = {k: v for k, v in params.items() if k in allowed and v is not None}
    canon = "&".join(f"{k}={filtered[k]}" for k in sorted(filtered.keys()))
    return hmac_hex(secret, canon.encode("utf-8"))

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)

    p1 = sub.add_parser("legacy")
    p1.add_argument("--secret", required=True)
    p1.add_argument("--ticket-id", required=True)
    p1.add_argument("--action", required=True, choices=["approve","reject"])
    p1.add_argument("--expires", required=True)

    p2 = sub.add_parser("canonical")
    p2.add_argument("--secret", required=True)
    p2.add_argument("--ticket-id", required=True)
    p2.add_argument("--action", required=True, choices=["approve","reject"])
    p2.add_argument("--expires", required=True)
    p2.add_argument("--require", required=True)
    p2.add_argument("--version", required=True)
    p2.add_argument("--by", required=False)

    args = p.parse_args()

    if args.mode == "legacy":
        print(legacy(args.secret, args.ticket_id, args.action, args.expires))
    else:
        params = {
            "action": args.action,
            "by": args.by,
            "expires": args.expires,
            "require": args.require,
            "ticket_id": args.ticket_id,
            "version": args.version,
        }
        print(canonical(args.secret, params))

if __name__ == "__main__":
    main()

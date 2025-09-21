# utils/hmac_sig.py
from __future__ import annotations
import argparse, hmac, hashlib

def sig_legacy(secret: str, ticket_id: str, action: str, expires: str) -> str:
    base = f"{ticket_id}|{action}|{expires}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()

def sig_canonical(secret: str, **params) -> str:
    # canonical על מפתחות מוכרים, לפי סדר אלפביתי (ללא sig)
    allow = {"action","by","expires","require","ticket_id","version"}
    filt = {k: str(v) for k, v in params.items() if k in allow and v is not None}
    canon = "&".join(f"{k}={filt[k]}" for k in sorted(filt))
    return hmac.new(secret.encode("utf-8"), canon.encode("utf-8"), hashlib.sha256).hexdigest()

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)

    a = sub.add_parser("legacy")
    a.add_argument("--secret", required=True)
    a.add_argument("--ticket-id", required=True)
    a.add_argument("--action", required=True)
    a.add_argument("--expires", required=True)

    b = sub.add_parser("canonical")
    b.add_argument("--secret", required=True)
    b.add_argument("--ticket-id", required=True)
    b.add_argument("--action", required=True)
    b.add_argument("--expires", required=True)
    b.add_argument("--require")
    b.add_argument("--version")
    b.add_argument("--by")

    args = p.parse_args()
    if args.mode == "legacy":
        print(sig_legacy(args.secret, args.ticket_id, args.action, args.expires))
    else:
        print(sig_canonical(
            args.secret,
            ticket_id=args.ticket_id,
            action=args.action,
            expires=args.expires,
            require=args.require,
            version=args.version,
            by=args.by,
        ))

if __name__ == "__main__":
    main()


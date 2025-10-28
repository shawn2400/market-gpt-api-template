# utils/hmac_sig.py
from __future__ import annotations
import argparse
import base64
import hashlib
import hmac
import json
from typing import Dict, Iterable, List, Optional, Tuple, Union

# =========================
# Low-level helpers
# =========================
def _b(s: Union[str, bytes, bytearray]) -> bytes:
    return s if isinstance(s, (bytes, bytearray)) else str(s).encode("utf-8")

def _lower_keys(d: Dict[str, str]) -> Dict[str, str]:
    return {(k or "").lower(): v for k, v in (d or {}).items()}

def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _sha256_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")

def canonicalize_body(body: Union[None, str, bytes, bytearray, dict, list]) -> bytes:
    """
    Canonical JSON (compact) for dict/list, UTF-8 encode for str, passthrough for bytes.
    """
    if body is None:
        return b""
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    if isinstance(body, str):
        return body.encode("utf-8")
    try:
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except Exception:
        # Fall back to empty to avoid signature drift
        return b""


# =========================
# Legacy helper CLIs (kept as-is)
# =========================
def sig_legacy(secret: str, ticket_id: str, action: str, expires: str) -> str:
    base = f"{ticket_id}|{action}|{expires}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()

def sig_canonical(secret: str, **params) -> str:
    allow = {"action", "by", "expires", "require", "ticket_id", "version"}
    filt = {k: str(v) for k, v in params.items() if k in allow and v is not None}
    canon = "&".join(f"{k}={filt[k]}" for k in sorted(filt))
    return hmac.new(secret.encode("utf-8"), canon.encode("utf-8"), hashlib.sha256).hexdigest()


# =========================
# Internal (X-Timestamp/X-Nonce/X-Signature HEX) scheme
# Base string: "{route}|{ts}|{nonce}|{namespace}|{sha256(body)}"
# =========================
def build_internal_base(route: str, ts: Union[str, int], nonce: str, namespace: str, body: Union[str, bytes, dict, list, None]) -> bytes:
    ts_s = str(ts)
    body_bytes = canonicalize_body(body)
    return f"{route}|{ts_s}|{nonce}|{namespace}|{_sha256_hex(body_bytes)}".encode("utf-8")

def internal_signature_hex(secret: str, route: str, ts: Union[str, int], nonce: str, namespace: str, body: Union[str, bytes, dict, list, None]) -> str:
    base = build_internal_base(route, ts, nonce, namespace, body)
    return hmac.new(_b(secret), base, hashlib.sha256).hexdigest()


# =========================
# HTTP Signatures (HMAC-SHA256, Base64)
# String-To-Sign built strictly per headers="..." list
# - supports (request-target)
# =========================
def http_sig_build_string_to_sign(method: str, route_path: str, headers: Dict[str, str], headers_list: Iterable[str]) -> str:
    """
    Build the exact string-to-sign:
      - header names are lower-cased
      - "(request-target): <method-lower> <route_path>"
      - lines joined by "\n"
    """
    h = _lower_keys(headers or {})
    m = (method or "GET").lower()
    lines: List[str] = []
    for hn in headers_list:
        name_l = (hn or "").strip().lower()
        if name_l == "(request-target)":
            lines.append(f"(request-target): {m} {route_path}")
        else:
            lines.append(f"{name_l}: {h.get(name_l, '')}")
    return "\n".join(lines)

def http_signature_b64(secret: str, method: str, route_path: str, headers: Dict[str, str], headers_list: Iterable[str]) -> str:
    sts = http_sig_build_string_to_sign(method, route_path, headers, headers_list).encode("utf-8")
    return base64.b64encode(hmac.new(_b(secret), sts, hashlib.sha256).digest()).decode("ascii")

def make_authorization_signature_header(secret: str, key_id: str, method: str, route_path: str, headers: Dict[str, str], headers_list: Iterable[str]) -> str:
    """
    Build 'Authorization: Signature ...' value (without the 'Authorization: ' prefix).
    """
    sig_b64 = http_signature_b64(secret, method, route_path, headers, headers_list)
    hdrs = " ".join(h.strip().lower() for h in headers_list if h and str(h).strip())
    return f'Signature keyId="{key_id}",algorithm="hmac-sha256",headers="{hdrs}",signature="{sig_b64}"'


# =========================
# Optional CLI (handy for testing)
# =========================
def _cli_legacy(args: argparse.Namespace) -> None:
    print(sig_legacy(args.secret, args.ticket_id, args.action, args.expires))

def _cli_canonical(args: argparse.Namespace) -> None:
    print(sig_canonical(
        args.secret,
        ticket_id=args.ticket_id,
        action=args.action,
        expires=args.expires,
        require=args.require,
        version=args.version,
        by=args.by,
    ))

def _cli_internal(args: argparse.Namespace) -> None:
    body: Union[str, dict, list, None] = args.body
    try:
        if args.body_is_json:
            body = json.loads(args.body or "") if args.body else None
    except Exception:
        body = args.body  # fallback to raw
    print(internal_signature_hex(args.secret, args.route, args.ts, args.nonce, args.namespace, body))

def _cli_http(args: argparse.Namespace) -> None:
    headers: Dict[str, str] = {}
    for kv in args.header or []:
        if ":" in kv:
            k, v = kv.split(":", 1)
            headers[k.strip()] = v.strip()
    print(make_authorization_signature_header(args.secret, args.key_id, args.method, args.route_path, headers, args.headers_list))

def main():
    p = argparse.ArgumentParser(description="HMAC helpers: legacy/canonical/internal/http-signatures")
    sub = p.add_subparsers(dest="mode", required=True)

    # legacy
    a = sub.add_parser("legacy")
    a.add_argument("--secret", required=True)
    a.add_argument("--ticket-id", required=True)
    a.add_argument("--action", required=True)
    a.add_argument("--expires", required=True)
    a.set_defaults(func=_cli_legacy)

    # canonical
    b = sub.add_parser("canonical")
    b.add_argument("--secret", required=True)
    b.add_argument("--ticket-id", required=True)
    b.add_argument("--action", required=True)
    b.add_argument("--expires", required=True)
    b.add_argument("--require")
    b.add_argument("--version")
    b.add_argument("--by")
    b.set_defaults(func=_cli_canonical)

    # internal (HEX signature for X-* headers path)
    c = sub.add_parser("internal")
    c.add_argument("--secret", required=True)
    c.add_argument("--route", required=True, help='e.g. "POST /ops/approve/signed"')
    c.add_argument("--ts", required=True, help="epoch seconds")
    c.add_argument("--nonce", required=True)
    c.add_argument("--namespace", default="ops-supervisor-web")
    c.add_argument("--body", default="")
    c.add_argument("--body-is-json", action="store_true")
    c.set_defaults(func=_cli_internal)

    # http (Authorization: Signature ... )
    d = sub.add_parser("http")
    d.add_argument("--secret", required=True)
    d.add_argument("--key-id", default="ops-key")
    d.add_argument("--method", required=True)
    d.add_argument("--route-path", required=True, help='e.g. "/ops/approve/signed"')
    d.add_argument("--headers-list", required=True, nargs="+", help='e.g. (request-target) host x-ops-timestamp x-ops-nonce digest')
    d.add_argument("--header", action="append", help='Repeatable: "Name: value" to include in the signing set')
    d.set_defaults(func=_cli_http)

    args = p.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()



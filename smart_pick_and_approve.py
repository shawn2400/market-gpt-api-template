#!/usr/bin/env python3
# smart_pick_and_approve.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, hmac, hashlib, base64, time, secrets, http.client, urllib.parse, sys

G, R, N = "\033[32m", "\033[31m", "\033[0m"

BASE_URL = os.getenv("BASE_URL", os.getenv("PUBLIC_HOST", "https://algogpt-prod.onrender.com")).rstrip("/")
OPS_SIGN_SECRET = os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET")
CAP = int(os.getenv("PICK_CAP", "15"))

def _get_json(path: str):
    u = urllib.parse.urlparse(BASE_URL)
    Conn = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    conn = Conn(u.netloc, timeout=15)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        raw = resp.read()
        if resp.status != 200:
            print(f"{R}GET {path} -> {resp.status}{N}")
            return None
        return json.loads(raw.decode("utf-8", "replace"))
    finally:
        conn.close()

def _listify(js):
    if js is None: return []
    if isinstance(js, dict):
        for k in ("results", "items", "topk", "data", "suggestions"):
            if k in js and isinstance(js[k], list):
                return js[k]
        return [js] if js else []
    if isinstance(js, list): return js
    return []

def _score(x):
    for k in ("score", "quality", "quality_score", "qscore", "qs"):
        v = x.get(k)
        try: return float(v)
        except Exception: pass
    return -1.0

def _ticket(x):
    for k in ("ticket_id", "ticket", "id"):
        v = x.get(k)
        if isinstance(v, str) and v: return v
    return None

def _sym(x):
    for k in ("symbol", "sym", "pair"):
        v = x.get(k)
        if isinstance(v, str): return v.upper()
    return "?"

def _side(x):
    for k in ("side", "dir", "direction"):
        v = x.get(k)
        if isinstance(v, str): return v.upper()
    return "?"

def pick_best():
    for path in (f"/scan/public-topk?limit={CAP}", f"/scan/public-now?limit={CAP}", "/topk"):
        js = _get_json(path); arr = _listify(js)
        if not arr: continue
        arr = [a for a in arr if str(a.get("market", "futures")).lower().startswith("future")
               or "USDT" in str(a.get("symbol", "")).upper()]
        if not arr: continue
        best = max(arr, key=_score)
        return {
            "ticket_id": _ticket(best),
            "score": _score(best),
            "symbol": _sym(best),
            "side": _side(best),
            "raw": best,
        }
    return None

def approve_signed(ticket_id: str) -> bool:
    if not OPS_SIGN_SECRET:
        print(f"{R}Missing OPS_SIGN_SECRET/WEBHOOK_HMAC_SECRET{N}")
        sys.exit(2)

    u = urllib.parse.urlparse(BASE_URL)
    Conn = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    path = "/ops/approve/signed"

    body_dict = {"approve": True, "ticket_id": ticket_id}
    body = json.dumps(body_dict, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)
    digest_b64 = base64.b64encode(hashlib.sha256(body).digest()).decode("ascii")

    req_target = f"post {path}"
    headers_list = "(request-target) host content-type x-request-nonce x-request-timestamp digest"
    sig_string = "\n".join([
        f"(request-target): {req_target}",
        f"host: {u.netloc}",
        f"content-type: application/json",
        f"x-request-nonce: {nonce}",
        f"x-request-timestamp: {ts}",
        f"digest: SHA-256={digest_b64}",
    ])

    sec = OPS_SIGN_SECRET
    try:
        key = bytes.fromhex(sec) if len(sec) == 64 and all(c in "0123456789abcdefABCDEF" for c in sec) else sec.encode()
    except Exception:
        key = sec.encode()

    sig_b64 = base64.b64encode(hmac.new(key, sig_string.encode("utf-8"), hashlib.sha256).digest()).decode("ascii")
    auth_header = f'Signature keyId="ops",algorithm="hmac-sha256",headers="{headers_list}",signature="{sig_b64}"'

    headers = {
        "Content-Type": "application/json",
        "Host": u.netloc,
        "X-Request-Nonce": nonce,
        "X-Request-Timestamp": ts,
        "Digest": f"SHA-256={digest_b64}",
        "Authorization": auth_header,
    }

    conn = Conn(u.netloc, timeout=20)
    try:
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read().decode("utf-8", "replace")
        ok = 200 <= resp.status < 300
        print((G if ok else R) + f"approve/signed {resp.status}" + N)
        if data.strip():
            print(data)
        return ok
    finally:
        conn.close()

def main():
    print("Picking best ticket…")
    bt = pick_best()
    if not bt or not bt["ticket_id"]:
        print(f"{R}No candidates found (public-topk/now empty).{N}")
        sys.exit(1)
    print(f"{G}Best: {bt['symbol']} {bt['side']} | score={bt['score']:.2f} | ticket={bt['ticket_id']}{N}")
    ok = approve_signed(bt["ticket_id"])
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()

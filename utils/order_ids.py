# utils/order_ids.py
from __future__ import annotations
import hashlib, os, re, time

__all__ = ["build_client_order_id", "coid_fit"]

def coid_fit(s: str, limit: int = 32) -> str:
    if len(s) <= limit:
        return s
    h = hashlib.md5(s.encode("utf-8")).hexdigest()[:7]
    return f"{s[:limit-8]}_{h}"

def build_client_order_id(symbol: str, side: str, role: str = "ENTRY", extra: str | None = None) -> str:
    prefix = (os.getenv("ORDER_ID_PREFIX") or "ALG_MAIN").strip() or "ALG_MAIN"
    sym = str(symbol).upper(); sd = str(side).upper(); rl = str(role).upper()
    ts = int(time.time())
    base = f"{prefix}_{sym}_{sd}_{rl}_{ts}"
    if extra:
        base = f"{base}_{re.sub(r'[^A-Z0-9_]+', '', str(extra).upper())}"
    return coid_fit(base, 32)


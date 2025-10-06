# utils/order_ids.py
from __future__ import annotations
import hashlib, os, re, time
from typing import Optional

__all__ = ["build_client_order_id", "coid_fit"]

def coid_fit(s: str, limit: int = 32) -> str:
    if len(s) <= limit:
        return s
    h = hashlib.md5(s.encode("utf-8")).hexdigest()[:6]
    return f"{s[:limit-7]}{h}"

_ALPH = "0123456789abcdefghijklmnopqrstuvwxyz"
def _to_base36(n: int) -> str:
    if n <= 0:
        return "0"
    out = []
    while n:
        n, r = divmod(n, 36)
        out.append(_ALPH[r])
    return "".join(reversed(out))

def build_client_order_id(symbol: str, side: str, role: str = "ENTRY", extra: Optional[str] = None) -> str:
    """
    COID קצר, תמיד כולל ROLE (TP1/TP2/TP3/SL/BE/TRAIL), ולבסוף חותמת זמן base36.
    שמירה על <=32 תווים כדי לרצות את הבורסה ודוחות הבריאות.
    דוגמה: ALG_SOLUSDT_SELL_TP1_p3f8z
    """
    prefix = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
    sym = str(symbol).upper()
    sd  = str(side).upper()
    rl  = str(role).upper()
    tsb = _to_base36(int(time.time()))  # קצר משמעותית מ-int רגיל
    base = f"{prefix}_{sym}_{sd}_{rl}_{tsb}"
    if extra:
        base = f"{base}_{re.sub(r'[^A-Z0-9_]+', '', str(extra).upper())}"
    return coid_fit(base, 32)


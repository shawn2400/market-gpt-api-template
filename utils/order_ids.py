from __future__ import annotations
import os, re, time, hashlib
from typing import Optional

"""
כלי מרכזי לבניית newClientOrderId חוקי לבינאנס (Futures):
- תווים מותרים: . A-Z a-z 0-9 _ - : /
- אורך מרבי: 36
- חיתוך זהיר + hash קצר ליציבות יוניקיות
- role עובר סניטיזציה (ללא '@' וכדו')
"""

__all__ = ["build_client_order_id", "sanitize_coid", "coid_fit"]

# Binance regex (לפי הדוקו/פרקטיקה): ^[.A-Z:/a-z0-9_-]{1,36}$
_ALLOWED_RX = re.compile(r'[^A-Za-z0-9._:/-]')

def sanitize_coid(s: str, maxlen: int = 36) -> str:
    """מסנן תווים אסורים וחותך לאורך המותר."""
    return _ALLOWED_RX.sub("_", str(s))[:maxlen]

def coid_fit(s: str, maxlen: int = 36) -> str:
    """חותך באלג׳ יוניקי קצר אם חורגים מהאורך (אחרי סניטיזציה)."""
    s = sanitize_coid(s, maxlen * 4)  # buffer
    if len(s) <= maxlen:
        return s
    h = hashlib.md5(s.encode("utf-8")).hexdigest()[:6]
    head = s[: maxlen - (len(h) + 1)]
    return f"{head}_{h}"

def build_client_order_id(
    symbol: str,
    side: str,
    role: str = "ENTRY",
    extra: Optional[str] = None,
    maxlen: int = 36,
) -> str:
    """
    תבנית מומלצת:
      {PREFIX}-{SYM}-{SIDE}-{ROLE}-{TS}[-{EXTRA}]
    - PREFIX מ-ORDER_ID_PREFIX (ברירת מחדל ALG)
    - הכל עובר סניטיזציה + חיתוך <= maxlen
    """
    prefix = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
    sym = str(symbol or "").upper().strip()
    sd  = str(side or "").upper().strip()
    rl  = str(role or "").upper().strip().replace("@", "_")
    ts  = str(int(time.time() * 1000))
    parts = [prefix, sym, sd, rl, ts]
    if extra:
        parts.append(str(extra))
    base = "-".join(parts)
    return coid_fit(base, maxlen)



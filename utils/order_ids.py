# /app/utils/order_ids.py
from __future__ import annotations
import os, re, time, hashlib

__all__ = ["build_client_order_id", "coid_fit", "sanitize_coid"]

# Binance allows: ^[.A-Z:/a-z0-9_-]{1,36}$
_SAFE = re.compile(r'[^A-Za-z0-9._:/-]')

def sanitize_coid(s: str, maxlen: int = 36) -> str:
    """Replace illegal chars and trim to maxlen."""
    return _SAFE.sub("_", str(s))[:maxlen]

def coid_fit(s: str, maxlen: int = 36) -> str:
    """Trim with tiny hash suffix if we overflow, still after sanitation."""
    s = sanitize_coid(s, maxlen*3)  # sanitize first on a longer buffer
    if len(s) <= maxlen:
        return s
    # keep most-left, add short hash for uniqueness
    h = hashlib.md5(s.encode("utf-8")).hexdigest()[:6]
    head = s[: maxlen - (len(h) + 1)]
    return f"{head}_{h}"

def build_client_order_id(
    symbol: str,
    side: str,
    role: str = "ENTRY",
    extra: str | None = None,
    maxlen: int = 36,
) -> str:
    """
    Recommended COID:
      {PREFIX}-{SYM}-{SIDE}-{ROLE}-{TS}[-{EXTRA}]
    All parts sanitized, then trimmed to <= maxlen (36 by default).
    """
    prefix = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
    sym = str(symbol).upper().strip()
    sd  = str(side).upper().strip()
    rl  = str(role).upper().strip().replace("@", "_")   # נגד Illegal '@'
    ts  = int(time.time() * 1000)
    parts = [prefix, sym, sd, rl, str(ts)]
    if extra:
        parts.append(str(extra))
    base = "-".join(parts)
    return coid_fit(base, maxlen)


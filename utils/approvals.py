# utils/approvals.py
from __future__ import annotations

import os
import time
import math
import hashlib
import json
from typing import Dict, Any, List, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────────────
# Env helpers
# ──────────────────────────────────────────────────────────────────────────────
def _as_bool(s: Optional[str], default: bool = False) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "on"} if s is not None else default


def _as_float(s: Optional[str], default: float) -> float:
    try:
        return float(str(s).strip())
    except Exception:
        return default


def _as_int(s: Optional[str], default: int) -> int:
    try:
        return int(str(s).strip())
    except Exception:
        return default


# ──────────────────────────────────────────────────────────────────────────────
# Policy (ניתן לשליטה דרך .env)
# ──────────────────────────────────────────────────────────────────────────────
APPROVAL_ENABLED = _as_bool(os.getenv("APPROVAL_ENABLED", "1"), True)
APPROVAL_SUCCESS_MIN = _as_float(os.getenv("APPROVAL_SUCCESS_MIN", "60"), 60.0)
APPROVAL_RR_MIN = _as_float(os.getenv("APPROVAL_RR_MIN", "1.30"), 1.30)
MIN_TP_SL_DIFF_PCT = _as_float(os.getenv("MIN_TP_SL_DIFF_PCT", "0.15"), 0.15)
APPROVAL_MAX_SL_PCT = _as_float(os.getenv("APPROVAL_MAX_SL_PCT", "3.0"), 3.0)
MIN_NOTIONAL_USDT = _as_float(os.getenv("MIN_NOTIONAL_USDT", "5"), 5.0)
APPROVAL_REQUIRE_FRESH_PRICE = _as_bool(os.getenv("APPROVAL_REQUIRE_FRESH_PRICE", "1"), True)
PRICE_MAX_AGE_SEC = _as_int(os.getenv("PRICE_MAX_AGE_SEC", "10"), 10)
WATCHLIST_CSV = os.getenv("WATCHLIST", "") or os.getenv("HEALTH_SYMBOLS", "")
REQUIRE_IN_WATCHLIST = _as_bool(os.getenv("APPROVAL_REQUIRE_WATCHLIST", "1"), True)
APPROVAL_DUP_COOLDOWN_SEC = _as_int(os.getenv("APPROVAL_DUP_COOLDOWN_SEC", "300"), 300)
MAX_LEVERAGE = _as_int(os.getenv("MAX_LEVERAGE", "35"), 35)

# ──────────────────────────────────────────────────────────────────────────────
# State
# ──────────────────────────────────────────────────────────────────────────────
_recent: Dict[str, float] = {}  # key->last_ts


def _purge_recent(now: float) -> None:
    cut = now - max(60, APPROVAL_DUP_COOLDOWN_SEC)
    for k, ts in list(_recent.items()):
        if ts < cut:
            _recent.pop(k, None)


def _key_for(tp: Dict[str, Any]) -> str:
    base = {
        "symbol": str(tp.get("symbol", "")).upper(),
        "side": str(tp.get("side", "")).upper(),
        "entry": round(float(tp.get("entry", 0.0) or 0.0), 8),
        "sl": round(float(tp.get("sl", 0.0) or 0.0), 8),
        "tp1": round(float(tp.get("tp1", 0.0) or 0.0), 8),
        "lev": int(tp.get("leverage") or 0),
        "interval": str(tp.get("interval", "") or ""),
    }
    raw = json.dumps(base, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


# ──────────────────────────────────────────────────────────────────────────────
# Utils
# ──────────────────────────────────────────────────────────────────────────────
def _rr(entry: float, sl: float, tp1: float, side: str) -> Optional[float]:
    try:
        e = float(entry)
        s = float(sl)
        t = float(tp1)
        sd = (side or "").upper()
        risk = abs(e - s)
        if risk <= 0:
            return None
        reward = (t - e) if sd in ("BUY", "LONG") else (e - t)
        return float(reward / risk) if reward > 0 else None
    except Exception:
        return None


def _pct(a: float, b: float) -> float:
    try:
        return abs((a - b) / b) * 100.0
    except Exception:
        return 0.0


def _in_watchlist(sym: str) -> bool:
    if not REQUIRE_IN_WATCHLIST:
        return True
    wl = [x.strip().upper() for x in (WATCHLIST_CSV or "").split(",") if x.strip()]
    return (not wl) or (sym.upper() in wl)


def _fresh_price_ok(symbol: str) -> Tuple[bool, Optional[float]]:
    if not APPROVAL_REQUIRE_FRESH_PRICE:
        return (True, None)
    try:
        from utils.ws_fallback import is_price_fresh, get_price
        ok = is_price_fresh(symbol, max_age_sec=PRICE_MAX_AGE_SEC)
        px = float(get_price(symbol) or 0.0)
        return (bool(ok), px if px > 0 else None)
    except Exception:
        return (False, None)


def _aligned(val: float, step: float, tol: float = 1e-10) -> bool:
    if step <= 0:
        return True
    k = round(val / step)
    return abs(k * step - val) <= max(tol, step * 1e-8)


def _precision_checks(symbol: str, entry: float, sl: float, tp1: float) -> List[str]:
    """
    בדיקות tickSize/stepSize מתוך exchange_info.
    """
    out: List[str] = []
    try:
        from utils.binance_client import get_symbol_info
        info = get_symbol_info(symbol)
        if not info:
            return out
        tick = None
        for f in info.get("filters", []):
            if f.get("filterType") == "PRICE_FILTER":
                tick = float(f.get("tickSize", "0.0")) or None
        if tick:
            for name, val in [("entry", entry), ("sl", sl), ("tp1", tp1)]:
                if not _aligned(float(val), float(tick)):
                    out.append(f"{name}_not_aligned_tick({val})")
    except Exception:
        pass
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────
def preflight_proposal(tp: Dict[str, Any]) -> Dict[str, Any]:
    out_errors: List[str] = []
    out_warns: List[str] = []
    metrics: Dict[str, Any] = {}

    if not APPROVAL_ENABLED:
        return {"ok": True, "errors": [], "warnings": [], "metrics": {"disabled": True}}

    symbol = str(tp.get("symbol", "")).upper()
    side = str(tp.get("side", "")).upper()
    entry = float(tp.get("entry") or 0.0)
    sl = float(tp.get("sl") or 0.0)
    tp1 = float(tp.get("tp1") or 0.0)

    if not symbol:
        out_errors.append("missing_symbol")
    if side not in ("BUY", "SELL",






# utils/approvals.py
from __future__ import annotations
import os, time, math, hashlib, json
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
APPROVAL_ENABLED              = _as_bool(os.getenv("APPROVAL_ENABLED", "1"), True)
APPROVAL_SUCCESS_MIN          = _as_float(os.getenv("APPROVAL_SUCCESS_MIN", "60"), 60.0)
APPROVAL_RR_MIN               = _as_float(os.getenv("APPROVAL_RR_MIN", "1.30"), 1.30)
MIN_TP_SL_DIFF_PCT            = _as_float(os.getenv("MIN_TP_SL_DIFF_PCT", "0.15"), 0.15)
APPROVAL_MAX_SL_PCT           = _as_float(os.getenv("APPROVAL_MAX_SL_PCT", "3.0"), 3.0)
MIN_NOTIONAL_USDT             = _as_float(os.getenv("MIN_NOTIONAL_USDT", "5"), 5.0)
APPROVAL_REQUIRE_FRESH_PRICE  = _as_bool(os.getenv("APPROVAL_REQUIRE_FRESH_PRICE", "1"), True)
PRICE_MAX_AGE_SEC             = _as_int(os.getenv("PRICE_MAX_AGE_SEC", "10"), 10)
WATCHLIST_CSV                 = os.getenv("WATCHLIST", "") or os.getenv("HEALTH_SYMBOLS", "")
REQUIRE_IN_WATCHLIST          = _as_bool(os.getenv("APPROVAL_REQUIRE_WATCHLIST", "1"), True)
APPROVAL_DUP_COOLDOWN_SEC     = _as_int(os.getenv("APPROVAL_DUP_COOLDOWN_SEC", "300"), 300)
MAX_LEVERAGE                  = _as_int(os.getenv("MAX_LEVERAGE", "35"), 35)

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
        "symbol": str(tp.get("symbol","")).upper(),
        "side":   str(tp.get("side","")).upper(),
        "entry":  round(float(tp.get("entry", 0.0) or 0.0), 8),
        "sl":     round(float(tp.get("sl",    0.0) or 0.0), 8),
        "tp1":    round(float(tp.get("tp1",   0.0) or 0.0), 8),
        "lev":    int(tp.get("leverage") or 0),
        "interval": str(tp.get("interval","") or ""),
    }
    raw = json.dumps(base, sort_keys=True, separators=(",",":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]

# ──────────────────────────────────────────────────────────────────────────────
# Utils
# ──────────────────────────────────────────────────────────────────────────────
def _rr(entry: float, sl: float, tp1: float, side: str) -> Optional[float]:
    try:
        e = float(entry); s = float(sl); t = float(tp1)
        sd = (side or "").upper()
        risk  = abs(e - s)
        if risk <= 0: return None
        reward = (t - e) if sd in ("BUY","LONG") else (e - t)
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

def _precision_checks(symbol: str, entry: float, sl: float, tp1: float) -> List[str]:
    """
    בדיקות tickSize/stepSize מתוך exchange_info.
    """
    out: List[str] = []
    try:
        from utils.binance_client import get_symbol_info
        info = get_symbol_info(symbol)
        if not info: return out
        for f in info.get("filters", []):
            if f.get("filterType") == "PRICE_FILTER":
                tick = float(f.get("tickSize", "0.0"))
                if tick > 0:
                    for name, val in [("entry", entry), ("sl", sl), ("tp1", tp1)]:
                        if round(val / tick) * tick != val:
                            out.append(f"{name}_not_aligned_tick({val})")
            if f.get("filterType") == "LOT_SIZE":
                step = float(f.get("stepSize", "0.0"))
                minq = float(f.get("minQty", "0.0"))
                if step > 0 and minq > 0:
                    # רק בדיקות עקרוניות, הכמות בפועל נבדקת ב-executor
                    pass
    except Exception:
        pass
    return out

# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────
def preflight_proposal(tp: Dict[str, Any]) -> Dict[str, Any]:
    out_errors: List[str] = []
    out_warns:  List[str] = []
    metrics: Dict[str, Any] = {}

    if not APPROVAL_ENABLED:
        return {"ok": True, "errors": [], "warnings": [], "metrics": {"disabled": True}}

    symbol = str(tp.get("symbol","")).upper()
    side   = str(tp.get("side","")).upper()
    entry  = float(tp.get("entry") or 0.0)
    sl     = float(tp.get("sl") or 0.0)
    tp1    = float(tp.get("tp1") or 0.0)

    if not symbol: out_errors.append("missing_symbol")
    if side not in ("BUY","SELL","LONG","SHORT"): out_errors.append("bad_side")
    if entry <= 0: out_errors.append("bad_entry")
    if sl    <= 0: out_errors.append("bad_sl")
    if tp1   <= 0: out_errors.append("bad_tp1")

    if out_errors:
        return {"ok": False, "errors": out_errors, "warnings": out_warns, "metrics": metrics}

    if not _in_watchlist(symbol):
        out_errors.append("symbol_not_in_watchlist")

    fp_ok, px = _fresh_price_ok(symbol)
    metrics["fresh_price_ok"] = fp_ok
    metrics["last_price"] = px
    if not fp_ok: out_warns.append("stale_or_missing_price")

    min_pct = float(MIN_TP_SL_DIFF_PCT)
    if _pct(entry, sl) < min_pct:  out_errors.append(f"entry_sl_too_close(<{min_pct:.3f}%)")
    if _pct(entry, tp1) < min_pct: out_errors.append(f"entry_tp1_too_close(<{min_pct:.3f}%)")

    if _pct(entry, sl) > float(APPROVAL_MAX_SL_PCT):
        out_errors.append(f"sl_too_far(>{APPROVAL_MAX_SL_PCT:.2f}%)")

    rr = _rr(entry, sl, tp1, side)
    metrics["rr"] = rr
    if rr is None or rr < APPROVAL_RR_MIN:
        out_errors.append(f"rr_below_min({rr:.2f}<{APPROVAL_RR_MIN:.2f})" if rr is not None else "rr_invalid")

    sp = tp.get("success_pct")
    if sp is not None:
        try:
            spf = float(sp)
            metrics["success_pct"] = spf
            if spf < APPROVAL_SUCCESS_MIN:
                out_errors.append(f"success_pct_below_min({spf:.1f}<{APPROVAL_SUCCESS_MIN:.1f})")
        except Exception:
            out_warns.append("success_pct_not_numeric")

    lev = int(tp.get("leverage") or 0)
    if lev <= 0: out_warns.append("missing_leverage")
    elif lev > MAX_LEVERAGE: out_errors.append(f"leverage_above_cap(x{lev}>x{MAX_LEVERAGE})")
    metrics["leverage"] = lev

    budget = tp.get("budget")
    if budget is not None and lev > 0:
        try:
            notional = float(budget) * float(lev)
            metrics["notional_est"] = notional
            if notional < MIN_NOTIONAL_USDT:
                out_errors.append(f"notional_below_min(${notional:.2f} < ${MIN_NOTIONAL_USDT:.2f})")
        except Exception:
            out_warns.append("notional_est_failed")

    out_errors.extend(_precision_checks(symbol, entry, sl, tp1))

    now = time.time()
    _purge_recent(now)
    key = _key_for(tp)
    last = _recent.get(key)
    if last and (now - last < APPROVAL_DUP_COOLDOWN_SEC):
        out_errors.append("duplicate_recent")
    else:
        _recent[key] = now

    ok = (len(out_errors) == 0)
    return {"ok": ok, "errors": out_errors, "warnings": out_warns, "metrics": metrics}

def can_auto_forward(tp: Dict[str, Any]) -> bool:
    res = preflight_proposal(tp)
    return bool(res.get("ok", False))





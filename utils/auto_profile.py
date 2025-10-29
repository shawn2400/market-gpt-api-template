# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, json
from typing import Dict, Any, Optional, Tuple
from contextlib import suppress

try:
    import redis  # type: ignore
    _REDIS_URL = os.getenv("REDIS_URL", "").strip()
    _R = redis.Redis.from_url(_REDIS_URL, decode_responses=True) if _REDIS_URL else None
except Exception:
    _R = None

_STORE: Dict[str, Any] = {}

def _eni(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _enf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _day() -> str:
    # שמירה ב־UTC כדי לתאם מול שרתים
    return time.strftime("%Y-%m-%d", time.gmtime())

def _key(sym: str, field: str) -> str:
    return f"rg:{str(sym).upper()}:{field}"

def _get(sym: str, field: str, default: Any) -> Any:
    if _R:
        with suppress(Exception):
            v = _R.get(_key(sym, field))
            if v is not None:
                with suppress(Exception):
                    return json.loads(v)
                return v
    return _STORE.get(_key(sym, field), default)

def _set(sym: str, field: str, value: Any, ttl: Optional[int] = None) -> None:
    k = _key(sym, field)
    _STORE[k] = value
    if _R:
        with suppress(Exception):
            data = json.dumps(value)
            if ttl and ttl > 0:
                _R.setex(k, ttl, data)
            else:
                _R.set(k, data)

def note_trade_pnl(sym: str, pnl_usdt: float) -> None:
    rec = _get(sym, "pnl_day", {"day": _day(), "sum": 0.0})
    if rec.get("day") != _day():
        rec = {"day": _day(), "sum": 0.0}
    try:
        rec["sum"] = float(rec.get("sum", 0.0)) + float(pnl_usdt)
    except Exception:
        rec["sum"] = float(pnl_usdt) if pnl_usdt else 0.0
    _set(sym, "pnl_day", rec, ttl=86400)

def daily_loss_guard(sym: str) -> Tuple[bool, str]:
    max_loss = _enf("MAX_LOSS_PER_SYMBOL_USDT", 0.0)
    if max_loss <= 0:
        return True, "ok"
    rec = _get(sym, "pnl_day", {"day": _day(), "sum": 0.0})
    if rec.get("day") != _day():
        return True, "ok"
    try:
        if float(rec.get("sum", 0.0)) <= -abs(max_loss):
            return False, "daily_max_loss_reached"
    except Exception:
        pass
    return True, "ok"

def drawdown_guard(sym: str) -> Tuple[bool, str]:
    cap_pct = _enf("DRAWDOWN_GUARD_PCT", 0.0)
    if cap_pct <= 0:
        return True, "ok"
    # שמירה על ATH והפרש
    eq = float(_get(sym, "equity", 0.0) or 0.0)
    ath = float(_get(sym, "equity_ath", 0.0) or 0.0)
    if eq > ath:
        _set(sym, "equity_ath", eq)
        ath = eq
    if ath > 0:
        dd_pct = (ath - eq) / ath * 100.0
        if dd_pct >= cap_pct:
            return False, "equity_drawdown_guard"
    return True, "ok"

def set_equity(sym: str, equity_usdt: float) -> None:
    _set(sym, "equity", float(equity_usdt), ttl=86400)

def session_rule_guard() -> Tuple[bool, str]:
    """
    SESSION_BLOCK_UTC="0-1" יחסום טריידים בין 00:00 ל־01:00 UTC.
    תומך גם בחלון גלישה (למשל "22-2").
    """
    block = os.getenv("SESSION_BLOCK_UTC", "")
    if not block:
        return True, "ok"
    try:
        lo, hi = block.split("-", 1)
        lo = int(lo); hi = int(hi)
        h = int(time.gmtime().tm_hour)
        if lo <= hi:
            ok = not (lo <= h < hi)
        else:
            ok = not (h >= lo or h < hi)
        return (ok, "ok" if ok else "session_block")
    except Exception:
        return True, "ok"

def correlation_guard(beta: float) -> Tuple[bool, str]:
    cap = _enf("CORR_CAP_BETA", 0.0)
    if cap <= 0:
        return True, "ok"
    try:
        if abs(float(beta)) > cap:
            return False, "beta_correlation_cap"
    except Exception:
        pass
    return True, "ok"

def should_allow_trade(sym: str, *, beta: float = 1.0) -> Tuple[bool, str, str]:
    ok, rsn = daily_loss_guard(sym);       if not ok: return False, "daily", rsn
    ok, rsn = drawdown_guard(sym);         if not ok: return False, "drawdown", rsn
    ok, rsn = session_rule_guard();        if not ok: return False, "session", rsn
    ok, rsn = correlation_guard(beta);     if not ok: return False, "correlation", rsn
    return True, "ok", "ok"


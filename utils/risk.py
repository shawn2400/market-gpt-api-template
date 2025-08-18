# utils/risk.py
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
import math
import os

# קונפיג ברירת מחדל + ENV
try:
    from utils import config as cfg  # type: ignore
except Exception:
    class cfg:  # type: ignore
        MAX_LEVERAGE = int(os.getenv("MAX_LEVERAGE", "35"))
        SL_MIN_PCT = float(os.getenv("SL_MIN_PCT", "0.20"))
        SL_MAX_PCT = float(os.getenv("SL_MAX_PCT", "5.00"))
        TP_MIN_PCT = float(os.getenv("TP_MIN_PCT", "0.30"))
        TP_MAX_PCT = float(os.getenv("TP_MAX_PCT", "8.00"))

_DEFAULT_RISK_PCT_PER_TRADE = float(os.getenv("RISK_PCT_PER_TRADE", "0.02"))
_MAX_NOTIONAL_PER_TRADE     = float(os.getenv("MAX_NOTIONAL_PER_TRADE", "10000"))

def _pct_long(entry: float, sl: float, tp: float) -> Tuple[float, float]:
    return max(0.0, (entry - sl) / entry * 100.0), max(0.0, (tp - entry) / entry * 100.0)

def _pct_short(entry: float, sl: float, tp: float) -> Tuple[float, float]:
    return max(0.0, (sl - entry) / entry * 100.0), max(0.0, (entry - tp) / entry * 100.0)

def _side_ok(entry: float, sl: float, tp: Optional[float], side: str) -> bool:
    s = side.upper()
    if s == "LONG":
        return sl <= entry if tp is None else (sl <= entry <= tp)
    if s == "SHORT":
        return sl >= entry if tp is None else (tp <= entry <= sl)
    return False

def _kelly_like(confidence: Optional[float]) -> float:
    if confidence is None:
        return 1.0
    p = max(0.0, min(100.0, float(confidence))) / 100.0
    mult = 0.5 + (p - 0.5) * 2.0
    return float(max(0.5, min(1.5, mult)))

def _round_step(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.floor(x / step) * step

def _infer_qty_step(symbol: str) -> float:
    return 0.001  # ברירת מחדל (אפשר להרחיב בהמשך מול exchangeInfo)

def _build_constraints(symbol: str, leverage_cap: int, qty_step: float) -> Dict[str, Any]:
    return {
        "max_leverage": leverage_cap,
        "qty_step": qty_step,
        "max_notional_per_trade": _MAX_NOTIONAL_PER_TRADE,
        "risk_pct_per_trade": _DEFAULT_RISK_PCT_PER_TRADE,
    }

def suggest_risk(
    *,
    symbol: str,
    side: str,
    entry: float,
    sl: float,
    tp: Optional[float] = None,
    atr: Optional[float] = None,
    equity_usdt: Optional[float] = None,
    confidence: Optional[float] = None,
    max_budget_usdt: Optional[float] = None,
    max_leverage: Optional[int] = None,
) -> Dict[str, Any]:
    symbol = str(symbol).upper().strip()
    s = str(side).upper().strip()
    if entry <= 0 or sl <= 0 or s not in ("LONG", "SHORT") or not _side_ok(entry, sl, tp, s):
        raise ValueError("invalid inputs for side/entry/sl/tp")

    tp_eval = tp if tp else (entry * (1.003 if s == "LONG" else 0.997))

    if s == "LONG":
        sl_pct, tp_pct = _pct_long(entry, sl, tp_eval)
    else:
        sl_pct, tp_pct = _pct_short(entry, sl, tp_eval)

    leverage_cap = int(max(1, min(int(cfg.MAX_LEVERAGE), (max_leverage or cfg.MAX_LEVERAGE))))
    qty_step = _infer_qty_step(symbol)

    conf_mult = _kelly_like(confidence)
    risk_dollar_cap = float(equity_usdt) * _DEFAULT_RISK_PCT_PER_TRADE * conf_mult if equity_usdt else None

    if sl_pct <= 0:
        raise ValueError("SL distance must be positive")

    notional_max_by_risk = risk_dollar_cap / (sl_pct / 100.0) if risk_dollar_cap else None
    notional_cap_by_budget = (max_budget_usdt * leverage_cap) if max_budget_usdt else None

    candidates = [_MAX_NOTIONAL_PER_TRADE]
    if notional_max_by_risk:
        candidates.append(notional_max_by_risk)
    if notional_cap_by_budget:
        candidates.append(notional_cap_by_budget)

    notional_target = min(candidates)
    leverage = leverage_cap
    budget_usdt = notional_target / leverage
    qty = _round_step(notional_target / entry, qty_step)

    return {
        "ok": True,
        "suggested": {
            "symbol": symbol,
            "side": s,
            "budget_usdt": round(budget_usdt, 2),
            "leverage": leverage,
            "qty": qty,
            "notional_usdt": round(qty * entry, 2),
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "sl_pct": round(sl_pct, 4),
            "tp_pct": round(tp_pct, 4),
            "qty_step": qty_step,
        },
        "inputs": {
            "equity_usdt": equity_usdt,
            "confidence": confidence,
            "max_budget_usdt": max_budget_usdt,
            "max_leverage": max_leverage,
            "atr": atr,
        },
        "constraints": _build_constraints(symbol, leverage_cap, qty_step),
    }

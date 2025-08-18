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
        # מרחקי SL/TP מסייעים לבדיקות בצד הראוטר, אבל נשתמש גם כאן כשאין TP
        SL_MIN_PCT = float(os.getenv("SL_MIN_PCT", "0.20"))
        SL_MAX_PCT = float(os.getenv("SL_MAX_PCT", "5.00"))
        TP_MIN_PCT = float(os.getenv("TP_MIN_PCT", "0.30"))
        TP_MAX_PCT = float(os.getenv("TP_MAX_PCT", "8.00"))

# פרמטרים שמרניים לברירת מחדל
_DEFAULT_RISK_PCT_PER_TRADE = float(os.getenv("RISK_PCT_PER_TRADE", "0.02"))   # 2% הון/טרייד
_MAX_NOTIONAL_PER_TRADE     = float(os.getenv("MAX_NOTIONAL_PER_TRADE", "10000"))  # תקרה קשה לנקוב דולר

def _pct_long(entry: float, sl: float, tp: float) -> Tuple[float, float]:
    return max(0.0, (entry - sl) / entry * 100.0), max(0.0, (tp - entry) / entry * 100.0)

def _pct_short(entry: float, sl: float, tp: float) -> Tuple[float, float]:
    return max(0.0, (sl - entry) / entry * 100.0), max(0.0, (entry - tp) / entry * 100.0)

def _side_ok(entry: float, sl: float, tp: Optional[float], side: str) -> bool:
    s = side.upper()
    if s == "LONG":
        if tp is None:
            return sl <= entry
        return (sl <= entry <= tp)
    if s == "SHORT":
        if tp is None:
            return sl >= entry
        return (tp <= entry <= sl)
    return False

def _kelly_like(confidence_0_100: Optional[float]) -> float:
    """
    ממפה confidence (0..100) למשקולת תקציב: 0.5..1.5 (שמרני).
    55 → ~1.0 ; 70 → ~1.25 ; 40 → ~0.8
    """
    if confidence_0_100 is None:
        return 1.0
    p = max(0.0, min(100.0, float(confidence_0_100))) / 100.0
    # Kelly simplified around 50% base; clamp to [0.5, 1.5]
    mult = 0.5 + (p - 0.5) * 2.0  # p=0.5 → 0.5 ; p=1.0 → 1.5 ; p=0.0 → -0.5 (נחתוך)
    return float(max(0.5, min(1.5, mult)))

def _round_step(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.floor(x / step) * step

def _infer_qty_step(symbol: str) -> float:
    """
    אפשר לחבר ל-Exchange Info כדי להביא lotSize/stepSize. כרגע ברירת מחדל שמרנית.
    """
    # לדוגמה: רוב perpetuals באחוזי מטבע של 0.001/0.01
    return 0.001

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
    confidence: Optional[float] = None,     # 0..100
    max_budget_usdt: Optional[float] = None,
    max_leverage: Optional[int] = None,
) -> Dict[str, Any]:
    """
    מחשב תקציב, מינוף וכמות (Qty) תחת אילוצי סיכון.
    פלט: { ok, suggested:{budget_usdt, leverage, qty, notional, side}, inputs:{...}, constraints, note? }
    """
    symbol = str(symbol).upper().strip()
    s = str(side).upper().strip()
    if entry <= 0 or sl <= 0 or s not in ("LONG", "SHORT") or not _side_ok(entry, sl, tp, s):
        raise ValueError("invalid inputs for side/entry/sl/tp")

    # מרחק SL באחוזים — דרוש כדי לאמוד הפסד/סיכון
    if tp is None:
        # אם אין TP, נשתמש רק ב-SL כדי לאמוד סיכון
        tp_eval = entry * (1.0 + (cfg.TP_MIN_PCT/100.0)) if s == "LONG" else entry * (1.0 - (cfg.TP_MIN_PCT/100.0))
    else:
        tp_eval = float(tp)

    if s == "LONG":
        sl_pct, tp_pct = _pct_long(entry, sl, tp_eval)
    else:
        sl_pct, tp_pct = _pct_short(entry, sl, tp_eval)

    # תקרות ברירת מחדל
    leverage_cap = int(max(1, min(int(cfg.MAX_LEVERAGE), (max_leverage or cfg.MAX_LEVERAGE))))
    qty_step = _infer_qty_step(symbol)

    # בסיס תקציב:
    # 1) risk_pct * equity → סיכון דולרי מקסימלי (אם equity קיים)
    # 2) max_budget_usdt ככובע קשיח
    # 3) confidence ממתן/מגדיל
    conf_mult = _kelly_like(confidence)
    risk_dollar_cap = None
    if equity_usdt and equity_usdt > 0:
        risk_dollar_cap = float(equity_usdt) * _DEFAULT_RISK_PCT_PER_TRADE * conf_mult  # סיכון מקסימלי
    # אם אין equity — נשתמש רק ב-max_budget_usdt כמסגרת תקציב

    # נחשב notional לפי מינוף:  notional = budget * leverage
    # כדי שההפסד ב-SL לא יעלה על risk_dollar_cap (אם קיים).
    # Loss at SL ≈ notional * (sl_pct/100). לכן:
    # notional_max_by_risk = risk_dollar_cap / (sl_pct/100)
    if sl_pct <= 0:
        # SL לא במרחק חיובי → לא ניתן לאמוד סיכון
        raise ValueError("SL distance must be positive")

    notional_max_by_risk = None
    if risk_dollar_cap:
        notional_max_by_risk = float(risk_dollar_cap) / (sl_pct / 100.0)

    # notional מקסימלי לפי תקציב וכובע קשיח
    budget_cap = float(max_budget_usdt) if (max_budget_usdt and max_budget_usdt > 0) else None
    notional_cap_by_budget = float(budget_cap * leverage_cap) if budget_cap else None

    # כובע קשיח כללי
    hard_cap = _MAX_NOTIONAL_PER_TRADE

    # בחר notional יעד: המינימום מכל הכובעים שקיימים
    candidates = [hard_cap]
    if notional_max_by_risk:
        candidates.append(notional_max_by_risk)
    if notional_cap_by_budget:
        candidates.append(notional_cap_by_budget)

    notional_target = min(candidates) if candidates else hard_cap
    notional_target = max(0.0, float(notional_target))

    # ממיר ל-budget ול-qty
    # budget_usdt = notional / leverage
    # qty = notional / entry
    leverage = max(1, min(leverage_cap, int(round(leverage_cap))))  # שלם
    if notional_cap_by_budget and notional_target > notional_cap_by_budget:
        # במקרה נדיר של rounding
        notional_target = notional_cap_by_budget
    budget_usdt = notional_target / float(leverage) if leverage > 0 else notional_target
    qty = notional_target / float(entry) if entry > 0 else 0.0
    qty = _round_step(qty, qty_step)

    # החזר פרטים
    suggested = {
        "symbol": symbol,
        "side": s,
        "budget_usdt": round(budget_usdt, 2),
        "leverage": int(leverage),
        "qty": float(qty),
        "notional_usdt": round(qty * entry, 2),
        "entry": float(entry),
        "sl": float(sl),
        "tp": float(tp) if tp is not None else None,
        "sl_pct": round(sl_pct, 4),
        "tp_pct": round(tp_pct, 4),
        "qty_step": qty_step,
    }

    inputs = {
        "equity_usdt": float(equity_usdt) if equity_usdt is not None else None,
        "confidence": float(confidence) if confidence is not None else None,
        "max_budget_usdt": float(max_budget_usdt) if max_budget_usdt is not None else None,
        "max_leverage": int(max_leverage) if max_leverage is not None else None,
        "atr": float(atr) if atr is not None else None,
    }

    constraints = _build_constraints(symbol, leverage_cap, qty_step)

    note = None
    if notional_max_by_risk and notional_target == notional_max_by_risk:
        note = "capped_by_risk_pct"
    if notional_cap_by_budget and notional_target == notional_cap_by_budget:
        note = (note + "|capped_by_budget") if note else "capped_by_budget"
    if notional_target == hard_cap:
        note = (note + "|capped_by_hard_cap") if note else "capped_by_hard_cap"

    return {
        "ok": True,
        "suggested": suggested,
        "inputs": inputs,
        "constraints": constraints,
        "note": note,
    }


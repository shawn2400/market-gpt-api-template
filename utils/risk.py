# utils/risk.py
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple, Literal

Side = Literal["LONG", "SHORT"]

def _to_float(name: str, default: float) -> float:
    try:
        v = os.getenv(name)
        return float(v) if v is not None else default
    except Exception:
        return default

def _to_int(name: str, default: int) -> int:
    try:
        v = os.getenv(name)
        return int(v) if v is not None else default
    except Exception:
        return default

@dataclass(frozen=True)
class RiskConfig:
    # תקרות מערכת (נטענות מה-ENV אם קיימות)
    max_leverage: int        = _to_int("MAX_LEVERAGE", 35)
    max_trade_budget: float  = _to_float("MAX_TRADE_BUDGET", 100.0)  # USD margin per trade
    # ניהול סיכונים (אופציונלי)
    risk_pct_per_trade: float = _to_float("RISK_PCT_PER_TRADE", 0.01)  # 1% מהיתרה
    # SL מחושב לפי ATR בהיעדר SL מפורש
    atr_mult_for_sl: float   = _to_float("ATR_MULT_FOR_SL", 1.5)
    # גבולות קיצון ל-SL כדי לא לאפשר SL הזוי (באחוזים יחסית ל-entry)
    min_sl_pct: float        = _to_float("MIN_SL_PCT", 0.0025)  # 0.25%
    max_sl_pct: float        = _to_float("MAX_SL_PCT", 0.05)    # 5%
    # עיגול דיפולטי לכמויות/מחירים אם לא סופקו precision חיצוניים
    default_qty_step: float  = _to_float("DEFAULT_QTY_STEP", 0.0001)
    default_price_tick: float= _to_float("DEFAULT_PRICE_TICK", 0.01)

def cap_leverage(requested: int, cfg: RiskConfig) -> int:
    requested = max(1, int(requested or 1))
    return min(requested, int(cfg.max_leverage))

def _round_to_step(x: float, step: Optional[float]) -> float:
    if not step or step <= 0:
        return x
    return (int(x / step)) * step

def _sl_distance_pct(entry: float, sl: Optional[float], atr: Optional[float], cfg: RiskConfig) -> float:
    if entry <= 0:
        raise ValueError("entry must be > 0")
    if sl is not None:
        d = abs(entry - float(sl)) / entry
    elif atr is not None:
        d = (float(atr) * cfg.atr_mult_for_sl) / entry
    else:
        raise ValueError("Either sl or atr must be provided")
    # קלמפ לגבולות קיצון
    return max(cfg.min_sl_pct, min(cfg.max_sl_pct, d))

def suggest_sl(entry: float, side: Side, sl: Optional[float], atr: Optional[float], cfg: RiskConfig) -> float:
    """החזרת SL (אם לא הגיע) לפי ATR*mult, תוך כיבוד min/max pct."""
    if sl is not None:
        return float(sl)
    if atr is None:
        raise ValueError("SL missing and ATR not provided")
    d_pct = _sl_distance_pct(entry, None, atr, cfg)
    if side == "LONG":
        return entry * (1.0 - d_pct)
    else:
        return entry * (1.0 + d_pct)

def qty_by_budget(entry: float, budget_usd: float, leverage: int) -> float:
    """כמות מקסימלית לפי מרג'ין נתון (budget) ומינוף: notional = budget*leverage, qty = notional/entry"""
    if entry <= 0:
        raise ValueError("entry must be > 0")
    notional = max(0.0, float(budget_usd)) * int(leverage)
    return notional / entry

def qty_by_risk(entry: float, sl: float, balance_usd: float, risk_pct: float) -> float:
    """
    כמות לפי סיכון כספי: הפסד ליחידה = |entry - sl|, הפסד מותר = balance*risk_pct,
    לכן qty = allowed_loss / |entry-sl|.
    (בחוזה USDT לינארי המינוף לא משנה את הפסד ליחידה — רק את הדרישה למרג'ין.)
    """
    loss_per_unit = abs(entry - sl)
    if entry <= 0 or loss_per_unit <= 0:
        raise ValueError("entry and sl must be valid and different")
    allowed = max(0.0, float(balance_usd)) * max(0.0, float(risk_pct))
    return allowed / loss_per_unit if allowed > 0 else 0.0

def suggest_order(
    *,
    entry: float,
    side: Side,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    atr: Optional[float] = None,
    leverage_req: int = 10,
    budget_usd: Optional[float] = None,     # אם לא סופק – ישתמש ב-max_trade_budget מה-ENV
    balance_usd: Optional[float] = None,    # לשיטת risk_pct
    qty_step: Optional[float] = None,
    price_tick: Optional[float] = None,
    cfg: Optional[RiskConfig] = None,
) -> Dict[str, Any]:
    """
    אלגוריתם:
      1) קבע מינוף חוקי (cap_leverage).
      2) גזור SL אם חסר (ATR*mult), וכפוף לגבולות min/max.
      3) חשב כמות לפי שני קריטריונים:
         - תקרת notional מהמרג'ין: qty_budget = (budget*leverage)/entry
         - סיכון כספי: qty_risk = (balance*risk_pct) / |entry-sl|
         * אם balance/risk_pct לא סופק – נשתמש רק בתקרת budget.
      4) בחר את המינימום מביניהם (אם qty_risk > 0), ועגל ל-step.
      5) החזר גם notional, וידואי בטיחות, והערות.

    מחזיר:
      {
        ok, entry, side, leverage, sl, tp, qty, notional,
        risk_amount_used, risk_pct_of_balance, constraints, notes
      }
    """
    cfg = cfg or RiskConfig()
    notes: list[str] = []

    # 1) מינוף
    leverage = cap_leverage(leverage_req, cfg)
    if leverage != leverage_req:
        notes.append(f"leverage capped to {leverage} (max_leverage={cfg.max_leverage})")

    # 2) SL
    sl_price = suggest_sl(entry, side, sl, atr, cfg)
    sl_pct = _sl_distance_pct(entry, sl_price, None, cfg)

    # 3) כמויות
    eff_budget = float(cfg.max_trade_budget if budget_usd is None else budget_usd)
    qty_cap_budget = qty_by_budget(entry, eff_budget, leverage)

    qty_risk_mode = False
    qty_risk_val = 0.0
    risk_amount_used = None
    risk_pct_of_balance = None
    if balance_usd is not None and cfg.risk_pct_per_trade > 0:
        qty_risk_mode = True
        qty_risk_val = qty_by_risk(entry, sl_price, balance_usd, cfg.risk_pct_per_trade)
        risk_amount_used = float(balance_usd) * float(cfg.risk_pct_per_trade)
        risk_pct_of_balance = cfg.risk_pct_per_trade

    if qty_risk_mode:
        qty_raw = min(qty_cap_budget, qty_risk_val)
        if qty_risk_val > qty_cap_budget:
            notes.append("qty limited by (budget * leverage) cap")
    else:
        qty_raw = qty_cap_budget

    # 4) עיגול לסטפים
    qty_step = qty_step or cfg.default_qty_step
    price_tick = price_tick or cfg.default_price_tick
    qty = max(0.0, _round_to_step(qty_raw, qty_step))
    notional = qty * entry

    # 5) בדיקות בטיחות בסיסיות
    if qty <= 0:
        return {
            "ok": False,
            "reason": "qty<=0 after constraints",
            "entry": entry,
            "side": side,
            "leverage": leverage,
            "sl": sl_price,
            "tp": tp,
            "qty": 0.0,
            "notional": 0.0,
            "notes": notes + ["quantity collapsed to 0 (check budget/leverage/risk settings)"],
        }

    # בדיקת כיוון SL (לא להפוך אותו לצד הלא נכון)
    if side == "LONG" and sl_price >= entry:
        notes.append("SL above or equal to entry for LONG -> adjusting to minimal valid SL")
        sl_price = entry * (1.0 - sl_pct)
    if side == "SHORT" and sl_price <= entry:
        notes.append("SL below or equal to entry for SHORT -> adjusting to minimal valid SL")
        sl_price = entry * (1.0 + sl_pct)

    # TP לא נכפה כאן (יש לך מודול SL/TP אחר); נשאיר כפי שסופק
    constraints = {
        "budget_usd": eff_budget,
        "max_trade_budget": cfg.max_trade_budget,
        "leverage_capped": leverage,
        "sl_pct": sl_pct,
        "qty_step": qty_step,
        "price_tick": price_tick,
    }

    return {
        "ok": True,
        "entry": entry,
        "side": side,
        "leverage": leverage,
        "sl": round(sl_price / price_tick) * price_tick if price_tick > 0 else sl_price,
        "tp": tp,
        "qty": qty,
        "notional": notional,
        "risk_amount_used": risk_amount_used,
        "risk_pct_of_balance": risk_pct_of_balance,
        "constraints": constraints,
        "notes": notes,
    }


def validate_sl_tp(entry: float, side: Side, sl: Optional[float], tp: Optional[float]) -> Tuple[bool, str]:
    """וולידציה בסיסית ל-SL/TP ביחס ל-entry והכיוון."""
    if entry <= 0:
        return False, "entry must be > 0"
    if sl is None:
        return False, "missing SL"
    if side == "LONG":
        if sl >= entry:
            return False, "SL must be below entry for LONG"
        if tp is not None and tp <= entry:
            return False, "TP must be above entry for LONG"
    else:
        if sl <= entry:
            return False, "SL must be above entry for SHORT"
        if tp is not None and tp >= entry:
            return False, "TP must be below entry for SHORT"
    return True, "ok"


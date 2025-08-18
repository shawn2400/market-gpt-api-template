# utils/risk.py
from __future__ import annotations

import math
import os
from typing import Dict, Any, Optional, List, Tuple, Literal

Side = Literal["LONG", "SHORT"]

# ------------------------
# ENV helpers & defaults
# ------------------------

def _env_float(k: str, d: float) -> float:
    try:
        v = float((os.getenv(k, "") or "").strip() or d)
        if math.isnan(v) or math.isinf(v):
            return d
        return v
    except Exception:
        return d

def _env_int(k: str, d: int) -> int:
    try:
        v = int((os.getenv(k, "") or "").strip() or d)
        return v
    except Exception:
        return d

def _env_bool(k: str, d: bool) -> bool:
    v = (os.getenv(k, "") or "").strip().lower()
    if v in ("1","true","yes","on"): return True
    if v in ("0","false","no","off"): return False
    return d

# Global risk knobs (tunable via .env)
MAX_TRADE_BUDGET      = _env_float("MAX_TRADE_BUDGET", 100.0)       # cap per trade (USDT)
MAX_LEVERAGE          = _env_int  ("MAX_LEVERAGE", 35)              # cap leverage
RISK_PER_TRADE_PCT    = _env_float("RISK_PER_TRADE_PCT", 1.0)       # % of equity risked per trade
DAILY_RISK_LIMIT_PCT  = _env_float("DAILY_RISK_LIMIT_PCT", 6.0)     # daily aggregate risk budget
PORTFOLIO_EXPOSURE_PCT= _env_float("PORTFOLIO_EXPOSURE_PCT", 25.0)  # max notional exposure % of equity
MAX_CONCURRENT_TRADES = _env_int  ("MAX_CONCURRENT_TRADES", 7)      # cap open trades
CONF_MIN_SCALE        = _env_float("CONF_MIN_SCALE", 0.6)           # confidence → risk scale floor
CONF_MAX_SCALE        = _env_float("CONF_MAX_SCALE", 1.4)           # confidence → risk scale ceiling
ATR_LEV_SENSITIVITY   = _env_float("ATR_LEV_SENSITIVITY", 0.9)      # how strongly ATR reduces leverage
TSL_TO_BE_FRACTION    = _env_float("TSL_TO_BE_FRACTION", 0.20)      # move SL 20% beyond BE after TP1

# ------------------------
# Safe numeric helpers
# ------------------------

def _clamp(x: float, lo: float, hi: float) -> float:
    if lo > hi:
        lo, hi = hi, lo
    return max(lo, min(hi, x))

def _abs(x: Optional[float]) -> float:
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v): return 0.0
        return abs(v)
    except Exception:
        return 0.0

# ------------------------
# Exchange precision helpers (best-effort)
# ------------------------

# Primary: precision_utils (rich constraints)
_px = None
try:
    from utils import precision_utils as _px  # type: ignore
except Exception:
    _px = None

# Secondary: calculate_quantity wrapper (already handles precision_utils internally)
_calc_qty = None
try:
    from utils.calculate_quantity import calculate_quantity as _calc_qty  # type: ignore
except Exception:
    _calc_qty = None

# Trade storage (to estimate portfolio exposure / open count)
_store = None
try:
    from trade_storage import load_open_trades, get_open_trades_count  # type: ignore
    _store = (load_open_trades, get_open_trades_count)
except Exception:
    _store = None

# ------------------------
# Core math
# ------------------------

def rr(entry: float, sl: float, tp: float, side: Side) -> Tuple[float, float, float]:
    """
    Returns (risk_abs, reward_abs, rr_ratio), absolute deltas in price units.
    """
    e = float(entry); s = float(sl); t = float(tp)
    if side == "LONG":
        risk   = max(0.0, e - s)
        reward = max(0.0, t - e)
    else:
        risk   = max(0.0, s - e)
        reward = max(0.0, e - t)
    ratio = (reward / risk) if risk > 0 else 0.0
    return (risk, reward, ratio)

def risk_at_sl_usd(entry: float, sl: float, budget: float, leverage: float) -> float:
    """
    Linear USDT-margined perp approximation:
    qty = (budget * leverage) / entry
    PnL at SL = |entry - sl| * qty  (absolute USD loss)
    """
    e = max(1e-9, float(entry))
    delta = _abs(entry - sl)
    qty = (float(budget) * float(leverage)) / e
    return float(delta * qty)

def budget_from_risk(entry: float, sl: float, leverage: float, risk_usd: float) -> float:
    """
    Solve for budget such that risk_at_sl_usd == risk_usd
    budget = risk_usd * entry / (leverage * |entry - sl|)
    """
    e = max(1e-9, float(entry))
    delta = _abs(entry - sl)
    L = max(1e-9, float(leverage))
    if delta <= 0:
        return 0.0
    return float((risk_usd * e) / (L * delta))

def leverage_from_budget(entry: float, sl: float, budget: float, risk_usd: float) -> float:
    """
    Solve for leverage such that risk_at_sl_usd == risk_usd
    leverage = risk_usd * entry / (budget * |entry - sl|)
    """
    e = max(1e-9, float(entry))
    delta = _abs(entry - sl)
    B = max(1e-9, float(budget))
    if delta <= 0:
        return 1.0
    return float((risk_usd * e) / (B * delta))

# ------------------------
# ATR-aware leverage cap
# ------------------------

def atr_scaled_leverage_cap(entry: float, atr: Optional[float], max_leverage: int = MAX_LEVERAGE) -> int:
    """
    Reduce max leverage when ATR is large vs entry.
    scale = 1 / (1 + ATR_LEV_SENSITIVITY * (atr/entry))
    """
    if not atr or atr <= 0 or entry <= 0:
        return int(max_leverage)
    ratio = float(atr) / float(entry)
    scale = 1.0 / (1.0 + ATR_LEV_SENSITIVITY * ratio)
    cap = int(max(1.0, math.floor(max_leverage * _clamp(scale, 0.2, 1.0))))
    return cap

# ------------------------
# Confidence scaling (0..100) → multiplier
# ------------------------

def confidence_scale(confidence: Optional[float]) -> float:
    """
    0 → CONF_MIN_SCALE , 50 → avg(=1.0 approx), 100 → CONF_MAX_SCALE
    Linear map.
    """
    if confidence is None:
        return 1.0
    c = _clamp(float(confidence), 0.0, 100.0)
    return float(CONF_MIN_SCALE + (CONF_MAX_SCALE - CONF_MIN_SCALE) * (c / 100.0))

# ------------------------
# Quantity helper (best effort)
# ------------------------

def calc_quantity(symbol: str, entry_price: float, budget_usdt: float, leverage: float) -> float:
    """
    Returns an exchange-conform quantity using best available utility.
    """
    # prefer precision_utils.calc_quantity_from_budget (rich)
    if _px is not None and hasattr(_px, "calc_quantity_from_budget"):
        try:
            res = _px.calc_quantity_from_budget(symbol=symbol, price=float(entry_price),
                                                budget_usd=float(budget_usdt), leverage=float(leverage))
            if isinstance(res, dict) and res.get("ok"):
                return float(res["qty"])
        except Exception:
            pass
    # secondary: calculate_quantity wrapper
    if _calc_qty is not None:
        try:
            return float(_calc_qty(symbol, float(entry_price), float(leverage), float(budget_usdt)))
        except Exception:
            pass
    # naive fallback (no precision anchoring)
    try:
        e = max(1e-9, float(entry_price))
        return float((float(budget_usdt) * float(leverage)) / e)
    except Exception:
        return 0.0

# ------------------------
# Portfolio guards
# ------------------------

def portfolio_open_count() -> int:
    if _store is None:
        return 0
    try:
        _, get_count = _store
        return int(get_count())
    except Exception:
        return 0

def portfolio_current_exposure() -> float:
    """
    Approximate current notional exposure (USDT) from trade_storage file.
    Sums budget*leverage for open trades that include those fields.
    """
    if _store is None:
        return 0.0
    try:
        load, _ = _store
        trades = load() or []
        expo = 0.0
        for t in trades:
            try:
                B = float(t.get("budget") or t.get("budget_usd") or 0.0)
                L = float(t.get("leverage") or 1.0)
                expo += max(0.0, B * L)
            except Exception:
                continue
        return float(expo)
    except Exception:
        return 0.0

# ------------------------
# Public API
# ------------------------

def suggest_budget_and_leverage(
    *,
    symbol: str,
    side: Side,
    entry: float,
    sl: float,
    tp: Optional[float],
    equity_usdt: float,
    confidence: Optional[float] = None,
    atr: Optional[float] = None,
    max_budget_usdt: Optional[float] = None,
    max_leverage: Optional[int] = None,
    risk_per_trade_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """
    מחשב תקציב ומינוף מומלצים כך שהסיכון ב-SL לא יעבור את אחוז הסיכון המבוקש מתוך הון התיק.
    משקלל:
      - בטחון (confidence) → סקייל לריסק
      - תקרות .env (MAX_TRADE_BUDGET / MAX_LEVERAGE / PORTFOLIO_EXPOSURE_PCT / MAX_CONCURRENT_TRADES)
      - הפחתת מינוף ביחס ל-ATR
    """
    # inputs & caps
    equity = max(0.0, float(equity_usdt))
    base_risk_pct = (RISK_PER_TRADE_PCT if risk_per_trade_pct is None else float(risk_per_trade_pct))
    base_risk_pct = _clamp(base_risk_pct, 0.1, 10.0)  # 0.1%..10%
    risk_scale = confidence_scale(confidence)
    eff_risk_pct = _clamp(base_risk_pct * risk_scale, 0.05, 12.0)

    maxL = int(MAX_LEVERAGE if max_leverage is None else int(max_leverage))
    # ATR cap
    maxL = min(maxL, atr_scaled_leverage_cap(entry, atr, max_leverage=maxL))
    maxB = float(MAX_TRADE_BUDGET if max_budget_usdt is None else float(max_budget_usdt))

    # portfolio guards
    open_cnt = portfolio_open_count()
    if open_cnt >= MAX_CONCURRENT_TRADES:
        return {
            "ok": False,
            "reason": f"max concurrent trades reached ({open_cnt}/{MAX_CONCURRENT_TRADES})",
            "suggested": None,
            "limits": {
                "max_concurrent_trades": MAX_CONCURRENT_TRADES,
            },
        }

    # exposure cap
    expo_cap = float(equity * (PORTFOLIO_EXPOSURE_PCT / 100.0))
    current_expo = portfolio_current_exposure()
    remaining_expo = max(0.0, expo_cap - current_expo)
    if remaining_expo <= 0.0:
        return {
            "ok": False,
            "reason": f"portfolio exposure cap reached ({current_expo:.2f}/{expo_cap:.2f} USDT)",
            "suggested": None,
            "limits": {"portfolio_exposure_pct": PORTFOLIO_EXPOSURE_PCT},
        }

    # target risk (USD)
    risk_usd_target = float(equity * (eff_risk_pct / 100.0))

    # strategy: try leverage around min( maxL, 10 ) first (sane default), then adjust
    # compute budget that fits risk at chosen leverage, then clamp to caps
    initial_L = min(maxL, 10)
    raw_budget = budget_from_risk(entry, sl, initial_L, risk_usd_target)
    # respect caps
    budget_capped = min(maxB, raw_budget)
    # respect exposure headroom: budget*L <= remaining_expo → B <= remaining_expo / L
    budget_capped = min(budget_capped, remaining_expo / max(1.0, initial_L))

    if budget_capped <= 0:
        return {
            "ok": False,
            "reason": "no budget headroom after exposure/limits",
            "suggested": None,
        }

    # if budget hit the cap too early, try to increase leverage (up to maxL) so that risk fits with a smaller budget
    if budget_capped < raw_budget and initial_L < maxL:
        # recompute leverage that satisfies risk with the capped budget
        needed_L = leverage_from_budget(entry, sl, budget_capped, risk_usd_target)
        L = int(_clamp(math.ceil(needed_L), 1, maxL))
    else:
        L = int(initial_L)

    # final budget re-solve (in case L changed)
    final_budget = budget_from_risk(entry, sl, L, risk_usd_target)
    final_budget = min(final_budget, maxB, remaining_expo / max(1.0, L))
    final_budget = max(0.0, float(final_budget))

    # compute quantity (exchange-safe if possible)
    qty = calc_quantity(symbol=symbol, entry_price=entry, budget_usdt=final_budget, leverage=L)

    # realized risk at SL with rounded qty (approximate back to budget space)
    # back-compute notional from qty to estimate realized risk more accurately
    notional = float(qty) * float(entry)
    # isolate margin approximated as budget ~= notional / leverage
    realized_budget = notional / max(1.0, float(L))
    realized_risk_usd = risk_at_sl_usd(entry, sl, realized_budget, L)

    r_abs, rew_abs, rr_ratio = rr(entry, sl, tp if tp is not None else entry, side)

    return {
        "ok": True,
        "suggested": {
            "budget_usd": round(final_budget, 2),
            "leverage": int(L),
            "qty": float(qty),
        },
        "risk": {
            "target_risk_usd": round(risk_usd_target, 2),
            "realized_risk_usd": round(realized_risk_usd, 2),
            "risk_pct_of_equity": round(100.0 * realized_risk_usd / max(1e-9, equity), 3),
        },
        "rr": {
            "risk_abs_price": r_abs,
            "reward_abs_price": rew_abs,
            "rr_ratio": round(rr_ratio, 3),
        },
        "limits": {
            "max_budget_usd": maxB,
            "max_leverage": maxL,
            "portfolio_exposure_cap_usd": round(expo_cap, 2),
            "portfolio_exposure_used_usd": round(current_expo, 2),
            "remaining_exposure_usd": round(remaining_expo, 2),
            "max_concurrent_trades": MAX_CONCURRENT_TRADES,
            "eff_risk_pct_per_trade": eff_risk_pct,
            "confidence_scale": risk_scale,
        },
        "notes": [
            "Budget/Leverage chosen to satisfy target risk at SL.",
            "ATR reduces max leverage cap dynamically." if (atr and atr > 0) else "ATR cap not applied.",
        ],
    }

def trailing_sl_after_tp1(
    *,
    entry: float,
    tp1: float,
    initial_sl: float,
    side: Side,
    fraction: Optional[float] = None,
) -> float:
    """
    מזיז SL אחרי TP1:
    - ברירת מחדל: ל-BE + fraction*distance_to_tp1 (LONG), או BE - fraction*distance_to_tp1 (SHORT)
    - fraction נשלטת ע"י TSL_TO_BE_FRACTION (דיפולט 0.20 = 20%)
    """
    f = TSL_TO_BE_FRACTION if fraction is None else float(fraction)
    f = _clamp(f, 0.0, 0.8)
    e = float(entry); t = float(tp1); s0 = float(initial_sl)
    be = e
    dist = abs(t - e)
    if side == "LONG":
        new_sl = max(s0, be + f * dist)
        # אל תעלה מעל TP1
        new_sl = min(new_sl, t * (1 - 1e-5))
    else:
        new_sl = min(s0, be - f * dist)
        # אל תרד מתחת TP1 (בכיוון SHORT)
        new_sl = max(new_sl, t * (1 + 1e-5))
    return round(float(new_sl), 6)

def is_trade_allowed_now(
    *,
    equity_usdt: float,
    pending_risk_usd: float = 0.0,
) -> Dict[str, Any]:
    """
    בדיקת חסםי פורטפוליו לפני פתיחת טרייד נוסף.
    """
    open_cnt = portfolio_open_count()
    if open_cnt >= MAX_CONCURRENT_TRADES:
        return {
            "ok": False,
            "reason": f"max concurrent trades reached ({open_cnt}/{MAX_CONCURRENT_TRADES})",
            "limits": {"max_concurrent_trades": MAX_CONCURRENT_TRADES},
        }
    expo_cap = float(equity_usdt * (PORTFOLIO_EXPOSURE_PCT / 100.0))
    current_expo = portfolio_current_exposure()
    if (current_expo + pending_risk_usd) > expo_cap:
        return {
            "ok": False,
            "reason": f"exposure cap exceeded: {current_expo + pending_risk_usd:.2f} > {expo_cap:.2f}",
            "limits": {"portfolio_exposure_pct": PORTFOLIO_EXPOSURE_PCT},
        }
    return {"ok": True}

# Optional: Kelly-like sizing (capped and safe)
def kelly_fraction(win_prob: float, rr_ratio: float, cap: float = 0.02) -> float:
    """
    Kelly simplified: f* = p - (1-p)/b, where b=RR.
    We cap to 'cap' (e.g. 2%) for safety and keep [0, cap].
    """
    p = _clamp(win_prob, 0.0, 1.0)
    b = max(1e-9, rr_ratio)
    f_star = p - (1.0 - p) / b
    return float(_clamp(f_star, 0.0, cap))

__all__ = [
    "suggest_budget_and_leverage",
    "risk_at_sl_usd",
    "budget_from_risk",
    "leverage_from_budget",
    "atr_scaled_leverage_cap",
    "confidence_scale",
    "calc_quantity",
    "portfolio_open_count",
    "portfolio_current_exposure",
    "trailing_sl_after_tp1",
    "is_trade_allowed_now",
    "kelly_fraction",
    "rr",
]



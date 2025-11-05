# -*- coding: utf-8 -*-
# utils/budget.py
from __future__ import annotations
import os, json, logging
from typing import Any, Dict, Optional

from utils.binance_client import (
    futures_balance, get_symbol_filters,
    DEFAULT_MIN_NOTIONAL,  # float default from ENV
)

logger = logging.getLogger("algogpt.budget")

__all__ = [
    "get_trade_budget_usdt",
    "get_dynamic_budget_for",
    "get_budget_usdt",
]

# ──────────────────────────────────────────────────────────────────────────────
# ENV helpers
# ──────────────────────────────────────────────────────────────────────────────
def _b(v: str, default: bool = False) -> bool:
    s = str(os.getenv(v, str(int(default)))).strip().lower()
    return s in ("1", "true", "yes", "on")

def _i(v: str, default: int = 0) -> int:
    try:
        return int(os.getenv(v, str(default)))
    except Exception:
        return default

def _f(v: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(v, str(default)))
    except Exception:
        return default

def _s(v: str, default: str = "") -> str:
    return os.getenv(v, default)

def _load_json_env(v: str, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    s = _s(v, "").strip()
    if not s:
        return default or {}
    try:
        return json.loads(s)
    except Exception as e:
        logger.warning("Invalid JSON in %s: %s", v, e)
        return default or {}

# ──────────────────────────────────────────────────────────────────────────────
# Equity (USDT) from futures balance
# ──────────────────────────────────────────────────────────────────────────────
def _get_equity_usdt(*, use_available: bool = True) -> float:
    """
    מביא Equity ב־USDT מחשבון Futures:
      • קודם מנסה availableBalance/withdrawAvailable
      • אם לא קיים — משתמש ב־walletBalance/balance/total
    """
    try:
        bals = futures_balance() or []
        for a in bals:
            asset = str(a.get("asset") or a.get("assetName") or "").upper()
            if asset != "USDT":
                continue
            if use_available:
                for k in ("availableBalance", "withdrawAvailable", "available"):
                    if k in a and a[k] is not None:
                        try:
                            return float(a[k])
                        except Exception:
                            pass
            # fallback total/wallet
            for k in ("walletBalance", "balance", "cashBalance", "total"):
                if k in a and a[k] is not None:
                    try:
                        return float(a[k])
                    except Exception:
                        pass
    except Exception as e:
        logger.error("equity fetch failed: %s", e)
        raise RuntimeError(f"FAIL-HARD: Cannot fetch equity from Binance API: {e}")
    
    # HARDENED: No silent 0.0 return - raise error if equity unavailable
    raise RuntimeError("FAIL-HARD: No USDT equity found in futures balance - cannot size positions safely")

# ──────────────────────────────────────────────────────────────────────────────
# Min Notional per symbol (USDT)
# ──────────────────────────────────────────────────────────────────────────────
def _min_notional_for(symbol: Optional[str]) -> float:
    if not symbol:
        return DEFAULT_MIN_NOTIONAL
    try:
        f = get_symbol_filters(symbol) or {}
        mn = f.get("minNotional")
        if mn is None:
            return DEFAULT_MIN_NOTIONAL
        return float(mn)
    except Exception:
        return DEFAULT_MIN_NOTIONAL

# ──────────────────────────────────────────────────────────────────────────────
# Quality tier table
# ──────────────────────────────────────────────────────────────────────────────
def _quality_multiplier(q: Optional[float]) -> float:
    """
    טבלת איכות דיפולטיבית — ניתנת להחלפה דרך BUDGET_QUALITY_TABLE_JSON.
    מבנה צפוי:
      { "10": 2.0, "9": 1.6, "8": 1.3, "7": 1.0, "0": 0.8 }
    לוגיקה: אם q>=key → מכפיל = value.
    """
    table = _load_json_env("BUDGET_QUALITY_TABLE_JSON", {
        "10": 2.0, "9": 1.6, "8": 1.3, "7": 1.0, "0": 0.8
    })
    if q is None:
        return 1.0
    try:
        # thresholds יורדים (גבוה→נמוך)
        tiers = sorted((int(k), float(v)) for k, v in table.items())
        tiers.sort(key=lambda kv: kv[0], reverse=True)
        qi = int(round(float(q)))
        for thr, mult in tiers:
            if qi >= thr:
                return max(0.1, float(mult))
        # לא נמצא, החזר אחרון
        return max(0.1, float(tiers[-1][1]) if tiers else 1.0)
    except Exception as e:
        logger.warning("quality table parse failed: %s", e)
        return 1.0

# ──────────────────────────────────────────────────────────────────────────────
# Volatility adjustment (optional)
# ──────────────────────────────────────────────────────────────────────────────
def _vol_multiplier(atr: Optional[float], price: Optional[float]) -> float:
    """
    התאמה לפי תנודתיות (ATR%):
      factor = 1 / (1 + sens * min(atr_pct, cap))
    ENV:
      • BUDGET_VOL_SENSITIVITY ∈ [0..3] (0=כבוי)
      • BUDGET_VOL_PCT_CAP (דיפולט 0.05 = 5%)
    """
    sens = _f("BUDGET_VOL_SENSITIVITY", 0.0)  # 0=כבוי
    if sens <= 0.0 or atr is None or price is None or price <= 0:
        return 1.0
    cap = _f("BUDGET_VOL_PCT_CAP", 0.05)
    atr_pct = abs(float(atr)) / float(price)
    atr_pct = min(max(atr_pct, 0.0), cap)
    try:
        factor = 1.0 / (1.0 + sens * atr_pct)
        return float(min(max(factor, 0.25), 1.25))
    except Exception:
        return 1.0

# ──────────────────────────────────────────────────────────────────────────────
# Main API
# ──────────────────────────────────────────────────────────────────────────────
def get_trade_budget_usdt(
    *,
    symbol: Optional[str] = None,
    quality: Optional[float] = None,
    atr: Optional[float] = None,
    price: Optional[float] = None,
) -> float:
    """
    מחזיר תקציב USDT לטרייד (margin, לא notional), דינמי או סטטי:
      • אם DYNAMIC_BUDGET_ENABLE=1 → דינמי לפי אחוז מההון + איכות + תנודתיות.
      • אחרת → חוזר לערך סטטי MAX_TRADE_BUDGET (תאימות לאחור).
    התקציב מוחל באופן אחיד על כל הסימבולים (דינמיקה גלובלית), למעט רצפת ה-minNotional.
    """
    # כבוי — סטטי
    if not _b("DYNAMIC_BUDGET_ENABLE", False):
        return _f("MAX_TRADE_BUDGET", 100.0)

    # בסיס: אחוז מההון הזמין/כולל
    use_avail = _b("BUDGET_USE_AVAILABLE_BALANCE", True)
    equity = _get_equity_usdt(use_available=use_avail)
    base_pct = _f("BUDGET_PCT_OF_EQUITY", 1.0)  # אחוז
    base = float(equity) * (float(base_pct) / 100.0)

    # מכפלה לפי איכות (אם יש ציון)
    q_mult = _quality_multiplier(quality)

    # התאמה לפי תנודתיות (אם סופק ATR+price)
    v_mult = _vol_multiplier(atr, price)

    # מכפלה גלובלית חיצונית (לפי רמת סיכון ידנית)
    risk_mult = _f("BUDGET_RISK_MULTIPLIER", 1.0)

    raw = base * q_mult * v_mult * risk_mult

    # רצפה/תקרה
    floor_usdt = _f("BUDGET_MIN_USDT", 5.0)
    ceil_usdt  = _f("BUDGET_MAX_USDT", 30.0)  # תקרה רכה - הורד מ-150 ל-30 כדי לאפשר 5-6 trades בו-זמנית
    hard_cap   = _f("BUDGET_HARD_CAP_USDT", 0.0)  # 0=כבוי
    if hard_cap > 0:
        ceil_usdt = min(ceil_usdt, hard_cap)

    budget = max(floor_usdt, min(raw, ceil_usdt))

    # הבטחת notional מינימלי לפי סימבול (אם הועבר)
    try:
        mn = _min_notional_for(symbol) if symbol else DEFAULT_MIN_NOTIONAL
        # אם התקציב הוא Margin — אין חובה להבטיח כאן נומינלי, אבל נשמור על רצפה מינימלית
        budget = max(budget, float(mn))
    except Exception:
        pass

    # לוג דיאגנוסטי (אופציונלי)
    if _b("LOG_BUDGET_DEBUG", False):
        logger.info({
            "event": "budget.calc",
            "equity": equity,
            "base_pct": base_pct,
            "quality": quality,
            "q_mult": q_mult,
            "v_mult": v_mult,
            "risk_mult": risk_mult,
            "raw": raw,
            "floor": floor_usdt,
            "ceil": ceil_usdt,
            "budget": budget
        })

    return float(budget)

# Alias נוח לשימוש בקוד קיים/חדש
def get_dynamic_budget_for(
    symbol: Optional[str] = None,
    *,
    score: Optional[float] = None,   # שם חלופי ל-quality
    quality: Optional[float] = None, # אם נשלח גם score וגם quality — נעדיף quality
    atr: Optional[float] = None,
    price: Optional[float] = None,
) -> float:
    """
    אותו הדבר כמו get_trade_budget_usdt — נשמר לשם קריא/אחיד.
    """
    q = quality if quality is not None else score
    return get_trade_budget_usdt(symbol=symbol, quality=q, atr=atr, price=price)

def get_budget_usdt(
    symbol: Optional[str] = None,
    *,
    quality: Optional[float] = None,
    atr: Optional[float] = None,
    price: Optional[float] = None,
) -> float:
    """
    מעטפת: אם דינמי דלוק → דינמי; אחרת → סטטי (MAX_TRADE_BUDGET).
    """
    if _b("DYNAMIC_BUDGET_ENABLE", False):
        return get_trade_budget_usdt(symbol=symbol, quality=quality, atr=atr, price=price)
    return _f("MAX_TRADE_BUDGET", 100.0)



# utils/risk.py
from __future__ import annotations
import logging, os
from typing import Optional, Dict, Any

log = logging.getLogger("algogpt.risk")

# ===== Optional deps (fallbacks if missing) =====
try:
    from utils.budget import get_trade_budget_usdt  # dynamic budget policy (env-driven)
except Exception:
    def get_trade_budget_usdt(*, symbol: str, quality: Optional[float] = None,
                              atr: Optional[float] = None, price: Optional[float] = None) -> float:
        """
        Fallback budget rule: ENV or default 25 USDT.
        """
        try:
            return float(os.getenv("DEFAULT_TRADE_BUDGET_USDT", "25"))
        except Exception:
            return 25.0

try:
    from utils.calculate_quantity import calculate_quantity  # respects exchange filters
except Exception:
    def calculate_quantity(*, symbol: str, entry_price: float, leverage: float, budget_usdt: float) -> float:
        """
        Fallback qty rule: naive division (no filters). Meant only to avoid import crash.
        """
        px = float(entry_price or 0.0)
        lev = max(1.0, float(leverage or 1.0))
        if px <= 0.0:
            raise ValueError("entry_price_must_be_positive")
        notional = float(budget_usdt) * lev
        qty = notional / px
        return round(qty, 8)

# ===== Public API =====
def choose_trade_budget(
    *,
    symbol: str,
    entry_price: Optional[float] = None,
    stop_price: Optional[float] = None,   # reserved
    quality_score: Optional[float] = None,
    atr: Optional[float] = None,
    price_hint: Optional[float] = None
) -> Dict[str, Any]:
    """
    בוחר תקציב טרייד (USDT) דינמי דרך utils.budget.get_trade_budget_usdt.
    """
    price_for_vol = float(entry_price) if entry_price else (float(price_hint) if price_hint else None)
    budget = float(get_trade_budget_usdt(
        symbol=symbol,
        quality=quality_score,
        atr=atr,
        price=price_for_vol
    ))
    return {"ok": budget > 0, "budget_usdt": round(budget, 2)}

def compute_position_size(
    *,
    symbol: str,
    side: str,
    entry_price: float,
    stop_price: Optional[float],
    leverage: float,
    quality_score: Optional[float] = None,
    atr: Optional[float] = None
) -> Dict[str, Any]:
    """
    - קובע תקציב (דינמי)
    - מחשב qty לפי התקציב, המחיר ודיוקי הסימבול.
    """
    bdg = choose_trade_budget(
        symbol=symbol,
        entry_price=entry_price,
        stop_price=stop_price,
        quality_score=quality_score,
        atr=atr,
    )
    if not bdg.get("ok"):
        return {"ok": False, "error": "budget_not_positive", "explain": bdg}

    budget = float(bdg["budget_usdt"])
    try:
        qty = calculate_quantity(
            symbol=symbol,
            entry_price=float(entry_price),
            leverage=float(leverage),
            budget_usdt=budget
        )
    except Exception as e:
        log.error("calculate_quantity error: %s", e)
        return {"ok": False, "error": str(e), "explain": bdg}

    return {
        "ok": True,
        "symbol": symbol.upper(),
        "side": str(side).upper(),
        "budget_usdt": round(budget, 2),
        "qty": qty,
        "entry_price": float(entry_price),
        "stop_price": float(stop_price) if stop_price else None,
        "leverage": float(leverage),
        "explain": bdg,
    }

def suggest_risk(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Shim תואם-ממשק לרואטרים ישנים: מחזיר המלצה בסיסית ובתקציב דינמי.
    לא מבצע אישור/ביצוע — אישורים מתבצעים רק דרך טלגרם (דינמי לפי ENV).
    """
    symbol = str(payload.get("symbol", "")).upper()
    entry = payload.get("entry") or payload.get("entry_price") or payload.get("price")
    sl = payload.get("sl") or payload.get("sl_price")
    lev = payload.get("leverage") or 10
    score = payload.get("score") or payload.get("quality") or None
    atr = payload.get("atr") or None

    bdg = choose_trade_budget(
        symbol=symbol,
        entry_price=float(entry) if entry else None,
        stop_price=float(sl) if sl else None,
        quality_score=float(score) if score is not None else None,
        atr=float(atr) if atr is not None else None,
    )
    try:
        out = {
            "ok": True,
            "suggestion": {
                "max_leverage": int(lev) if float(lev).is_integer() else float(lev),
                "budget": float(bdg.get("budget_usdt") or 0.0),
            },
            "explain": bdg,
        }
    except Exception:
        out = {"ok": True, "suggestion": {"max_leverage": 10, "budget": 25.0}, "explain": bdg}
    return out

__all__ = ["choose_trade_budget", "compute_position_size", "suggest_risk"]






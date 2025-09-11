# utils/risk.py
from __future__ import annotations
import logging
from typing import Optional, Dict, Any

from utils.budget import get_trade_budget_usdt
from utils.calculate_quantity import calculate_quantity

log = logging.getLogger("algogpt.risk")

def choose_trade_budget(
    *,
    symbol: str,
    entry_price: Optional[float] = None,
    stop_price: Optional[float] = None,   # עתידי
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
        "side": side.upper(),
        "budget_usdt": round(budget, 2),
        "qty": qty,
        "entry_price": float(entry_price),
        "stop_price": float(stop_price) if stop_price else None,
        "leverage": float(leverage),
        "explain": bdg,
    }






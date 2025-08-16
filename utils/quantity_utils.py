# utils/quantity_utils.py
from __future__ import annotations

import logging
from typing import Any, Optional, Dict

from utils.ws_fallback import get_price as ws_get_price, is_price_fresh
from utils.binance_client import client as binance_client  # פולבק נדיר למחיר
from utils.precision_utils import (
    get_precision_info as _get_precision_info_core,
    apply_price_tick as _apply_price_tick_core,
    apply_qty_step as _apply_qty_step_core,
    calc_quantity_from_budget as _calc_qty_from_budget_core,
)

PRICE_MAX_AGE_SEC = 10

# =============== Public API ===============
def get_precision_info(symbol: str) -> Dict[str, float]:
    return _get_precision_info_core(symbol)

def round_step(value: float, step: float) -> float:
    # נשמר לשמירת תאימות API ישן — היום משתמשים ב-apply_qty_step
    try:
        from math import floor
        if step <= 0:
            return float(value)
        return floor(float(value) / float(step)) * float(step)
    except Exception:
        return float(value)

def round_tick(price: float, tick_size: float) -> float:
    # תאימות API ישן — היום משתמשים ב-apply_price_tick
    try:
        from math import floor
        if tick_size <= 0:
            return float(price)
        return floor(float(price) / float(tick_size)) * float(tick_size)
    except Exception:
        return float(price)

def apply_price_tick(price: float, symbol: str):
    return _apply_price_tick_core(price, symbol)

def apply_qty_step(qty: float, symbol: str):
    return _apply_qty_step_core(qty, symbol)

# =============== Price Source (LIVE-first) ===============
async def get_live_price(symbol: str) -> Optional[float]:
    """
    מחיר לייב מ-WS (עדיף). אם לא זמין/לא טרי — פולבק ל-REST דרך python-binance.
    """
    try:
        p = await ws_get_price(symbol)
        if p is not None and is_price_fresh(symbol, max_age_sec=PRICE_MAX_AGE_SEC):
            return float(p)
    except Exception as e:
        logging.debug(f"[quantity_utils] WS price err {symbol}: {e}")

    # פולבק שמרני: REST
    try:
        t = binance_client.get_symbol_ticker(symbol=symbol.upper())
        price = float(t.get("price"))
        return price if price > 0 else None
    except Exception as e:
        logging.warning(f"[quantity_utils] REST price err {symbol}: {e}")
        return None

# =============== Quantity APIs ===============
def calculate_quantity(symbol: str, entry_price: float, leverage: float, budget_usdt: float) -> float:
    """
    מחשב כמות לפי תקציב×מינוף, כולל עמידה ב-stepSize/minQty/minNotional.
    מחזיר float בלבד (לשמירה על תאימות ישנה); אם נכשל — 0.0
    """
    try:
        res = _calc_qty_from_budget_core(symbol, price=float(entry_price), budget_usd=float(budget_usdt), leverage=float(leverage))
        if not res.get("ok"):
            logging.warning(f"[quantity_utils] calc_quantity fail {symbol}: {res}")
            return 0.0
        return float(res["qty"])
    except Exception as e:
        logging.error(f"[quantity_utils] ❌ calc_quantity error {symbol}: {e}")
        return 0.0

def calculate_quantity_usdt(symbol: str, usdt_amount: float, entry_price: Optional[float] = None, leverage: float = 1.0) -> float:
    """
    כמות לפי סכום USDT (עם אפשרות מחיר כניסה ידוע). אם לא סופק מחיר — תחושב כמות לפי מחיר לייב (פחות מומלץ לדיוק הזמנה).
    """
    try:
        price = float(entry_price) if entry_price is not None else None
        if price is None or price <= 0:
            logging.warning("[quantity_utils] entry_price not supplied — prefer passing it for deterministic rounding")
            return 0.0
        res = _calc_qty_from_budget_core(symbol, price=price, budget_usd=float(usdt_amount), leverage=float(leverage))
        if not res.get("ok"):
            logging.warning(f"[quantity_utils] calc_quantity_usdt fail {symbol}: {res}")
            return 0.0
        return float(res["qty"])
    except Exception as e:
        logging.error(f"[quantity_utils] ❌ calc_quantity_usdt error {symbol}: {e}")
        return 0.0

def auto_risk_allocation(symbol: str, risk_usd: float, entry_price: float, sl_pct: float) -> float:
    """
    הקצאת כמות לפי סיכון בדולרים: loss ≈ entry * qty * (sl_pct/100) ⇒ qty ≈ risk / (entry * sl_pct/100)
    כולל עיגון ל-step/minQty/minNotional.
    """
    try:
        if entry_price <= 0 or risk_usd <= 0 or sl_pct <= 0:
            return 0.0
        theo_qty = float(risk_usd) / (float(entry_price) * (float(sl_pct) / 100.0))
        # נשתמש ב-apply_qty_step + בדיקת מינימום נומינלי מול התקציב המינימלי הנדרש:
        res = _calc_qty_from_budget_core(symbol, price=float(entry_price), budget_usd=float(risk_usd), leverage=(100.0 / float(sl_pct)))
        if res.get("ok"):
            return float(res["qty"])
        # פולבק: עיגון סטפי בלבד
        q_adj, _ = _apply_qty_step_core(theo_qty, symbol)
        return float(q_adj) if q_adj > 0 else 0.0
    except Exception as e:
        logging.error(f"[quantity_utils] ❌ auto_risk_allocation error {symbol}: {e}")
        return 0.0











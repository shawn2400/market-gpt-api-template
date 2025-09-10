# utils/trade_manager.py
from __future__ import annotations
import time, logging, asyncio, json, os, math
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd

from utils import ws_fallback
from utils.indicators import atr, macd, adx
from utils.binance_client import (
    get_open_positions, get_klines_df, close_all_positions,
    get_open_orders, futures_cancel_order, futures_mark_price,
    futures_create_order, get_symbol_filters,
)

logger = logging.getLogger("algogpt.trade_manager")

# ──────────────────────────────────────────────────────────────────────────────
# ENV / Flags
# ──────────────────────────────────────────────────────────────────────────────
_COOLDOWN = int(os.getenv("TM_UPDATE_COOLDOWN_SEC", "30"))

_BE_GUARD_ENABLE = os.getenv("BE_GUARD_ENABLE", "1").lower() in ("1", "true", "yes", "on")
_BE_GUARD_EVERY_SEC = int(os.getenv("BE_GUARD_EVERY_SEC", "30"))
_TP1_TAGS: List[str] = [t.strip() for t in os.getenv("TP1_TAGS", "TP1,tp1,tp_1,TAKE_PROFIT_1").split(",") if t.strip()]
TP_BE_ONLY_AFTER_TP1 = os.getenv("TP_BE_ONLY_AFTER_TP1", "1").lower() in ("1","true","yes")
TP_BE_OFFSET_BPS = float(os.getenv("TP_BE_OFFSET_BPS", "5"))

# Prefix policy for cancels
ORDER_ID_PREFIX = os.getenv("ORDER_ID_PREFIX", "").strip()
CANCEL_ONLY_PREFIXED_ORDERS = os.getenv("CANCEL_ONLY_PREFIXED_ORDERS", "0").lower() in ("1","true","yes","on")
CANCEL_PREFIX_OVERRIDE = os.getenv("CANCEL_PREFIX_OVERRIDE", "").strip()

# Limit offsets (align עם trade_executor)
SL_LIMIT_OFFSET_BPS = float(os.getenv("SL_LIMIT_OFFSET_BPS", "8"))
TP_LIMIT_OFFSET_BPS = float(os.getenv("TP_LIMIT_OFFSET_BPS", "8"))

# Freeze Trailing (adaptive)
_TRAIL_FREEZE_ENABLE = os.getenv("TRAIL_FREEZE_ENABLE","0").lower() in ("1","true","yes","on")
_TRAIL_FREEZE_MIN_SEC = int(os.getenv("TRAIL_FREEZE_MIN_SEC","60"))
_TRAIL_FREEZE_MAX_SEC = int(os.getenv("TRAIL_FREEZE_MAX_SEC","180"))
_TRAIL_FREEZE_SPIKE_ATR_MULT = float(os.getenv("TRAIL_FREEZE_SPIKE_ATR_MULT", "1.8"))
_TRAIL_FREEZE_ADX_WEAK = float(os.getenv("TRAIL_FREEZE_ADX_WEAK", "20"))
_last_trail_freeze_until: Dict[str,float] = {}

# Daily Cap / KillSwitch
DAILY_LOSS_CAP = float(os.getenv("DAILY_HARD_LOSS_USD", "-150"))
_daily_pnl = 0.0
_trades_today: List[dict] = []
_cap_triggered = False

# Kill-Switch tracking
_health_fails = 0
_HEALTH_FAIL_MAX = int(os.getenv("KILLSWITCH_THRESHOLD", "3"))

REVIEW_PATH = Path("static/cache/trade_reviews.json")

# Optional Ops Guard (non-blocking)
try:
    from utils.ops_guard import ops_tick
except Exception:
    async def ops_tick(**kwargs): return None  # type: ignore

# Price age (optional)
try:
    get_price_age = ws_fallback.get_price_age  # type: ignore
except Exception:
    def get_price_age(symbol: str): return None  # type: ignore

# Config gates (presence only; לא נחסם אם חסר)
try:
    from utils.config import ALLOW_MANAGE_OPEN_TRADES, AUTO_RUN  # noqa: F401
except Exception:
    ALLOW_MANAGE_OPEN_TRADES, AUTO_RUN = True, True  # safe defaults

# Telegram notifier
from utils.telegram_notifier import (
    notify_sl_tp_update, notify_info,
    notify_error, notify_heartbeat,
    notify_daily_summary
)

# ──────────────────────────────────────────────────────────────────────────────
# Local quantizers (tick/step from exchangeInfo)
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_QTY_STEP = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))
DEFAULT_TICK     = float(os.getenv("DEFAULT_PRICE_TICK", "0.01"))

def _decimals(step_str: str) -> int:
    if "." not in step_str: return 0
    return len(step_str.split(".")[1].rstrip("0"))

def _filters(symbol: str) -> Dict[str, Any]:
    return get_symbol_filters(symbol) or {}

def _q_price(symbol: str, price: float) -> Tuple[str, float]:
    f = _filters(symbol); tick = float(f.get("tickSize") or DEFAULT_TICK) or DEFAULT_TICK
    decs = _decimals(str(f.get("tickSize") or DEFAULT_TICK))
    steps = round(price / tick); p = steps * tick
    s = f"{p:.{decs}f}"; return s, float(s)

def _q_qty(symbol: str, qty: float) -> Tuple[str, float]:
    f = _filters(symbol); step = float(f.get("stepSize") or DEFAULT_QTY_STEP) or DEFAULT_QTY_STEP
    decs = _decimals(str(f.get("stepSize") or DEFAULT_QTY_STEP))
    steps = math.floor(qty / step); q = max(step, steps * step)
    s = f"{q:.{decs}f}"; return s, float(s)

def _offset_bps(base: float, bps: float, sign: int) -> float:
    return base * (1.0 + sign * (bps / 10000.0))

# ──────────────────────────────────────────────────────────────────────────────
# Safe wrappers for SL/TP modify (fallback אם אין בביננס-קליינט)
# ──────────────────────────────────────────────────────────────────────────────
def _cancel_closing_orders(symbol: str, types: Tuple[str, ...]) -> int:
    """בטל הזמנות TP/SL פעילות לפי סוגים, בהתאם למדיניות פריפיקס."""
    try:
        orders = get_open_orders(symbol) or []
    except Exception:
        return 0
    pref = (CANCEL_PREFIX_OVERRIDE or ORDER_ID_PREFIX or "").strip()
    only_pref = CANCEL_ONLY_PREFIXED_ORDERS and bool(pref)
    tset = {t.upper() for t in types}
    count = 0
    for o in orders:
        st = (o.get("status") or "").upper()
        if st not in ("NEW","PARTIALLY_FILLED"): 
            continue
        typ = (o.get("type") or o.get("origType") or "").upper()
        if typ not in tset:
            continue
        if only_pref:
            coid = str(o.get("clientOrderId") or o.get("origClientOrderId") or "")
            if not coid.startswith(pref):
                continue
        oid = o.get("orderId")
        if oid is None: 
            continue
        try:
            futures_cancel_order(symbol, oid)
            count += 1
        except Exception as e:
            logger.warning("[tm.cancel] cancel failed %s/%s: %s", symbol, oid, e)
    return count

def modify_stop_loss(symbol: str, new_price: float, *, position_side: str = "LONG", qty_hint: Optional[float] = None) -> Dict[str, Any]:
    """
    Fallback modify: cancel active STOP/STOP_MARKET → place new STOP (limit)
    """
    sym = symbol.upper()
    close_side = "SELL" if position_side.upper() == "LONG" else "BUY"
    # ביטול ישנים
    _cancel_closing_orders(sym, ("STOP","STOP_MARKET"))
    # כימות
    stop_str, stop_px = _q_price(sym, float(new_price))
    limit_px = _offset_bps(stop_px, SL_LIMIT_OFFSET_BPS, -1 if close_side=="SELL" else +1)
    price_str, limit_px = _q_price(sym, float(limit_px))
    # כמות (אם לא נמסר רמז, ניקח מהפוזיציה)
    qty = qty_hint
    if not qty or qty <= 0:
        try:
            for p in get_open_positions(sym):
                amt = float(p.get("positionAmt") or 0.0)
                if abs(amt) > 0:
                    qty = abs(amt); break
        except Exception:
            pass
    if not qty or qty <= 0:
        return {"ok": False, "error": "qty_missing_for_modify_sl"}
    qty_str, _ = _q_qty(sym, float(qty))
    # שליחה
    try:
        resp = futures_create_order(
            symbol=sym, side=close_side, type="STOP", timeInForce="GTC",
            reduceOnly=True, stopPrice=stop_str, price=price_str, quantity=qty_str
        )
        return {"ok": True, "response": resp}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def modify_take_profit(symbol: str, new_price: float, *, position_side: str = "LONG", qty_hint: Optional[float] = None) -> Dict[str, Any]:
    """
    Fallback modify: cancel active TAKE_PROFIT/TAKE_PROFIT_MARKET → place new TAKE_PROFIT (limit)
    """
    sym = symbol.upper()
    close_side = "SELL" if position_side.upper() == "LONG" else "BUY"
    _cancel_closing_orders(sym, ("TAKE_PROFIT","TAKE_PROFIT_MARKET"))
    # כימות
    stop_str, stop_px = _q_price(sym, float(new_price))
    limit_px = _offset_bps(stop_px, TP_LIMIT_OFFSET_BPS, +1 if close_side=="SELL" else -1)
    price_str, limit_px = _q_price(sym, float(limit_px))
    # כמות
    qty = qty_hint
    if not qty or qty <= 0:
        try:
            for p in get_open_positions(sym):
                amt = flo















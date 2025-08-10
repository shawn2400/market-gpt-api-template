# utils/binance_trader.py
import math
import logging
from typing import Dict, Any, Optional, Tuple

from binance.exceptions import BinanceAPIException
from utils.binance_client import get_client, futures_exchange_info_safe, _retry_call  # _retry_call נחשף בעקיפין
from utils import config

_client = get_client()

# --- Cache לפילטרים כדי לא למשוך exchange_info כל פעם ---
_SYMBOL_FILTERS_CACHE: dict[str, dict] = {}

def _to_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)

def _floor_to_step(value: float, step: float, precision: int = 8) -> float:
    step = float(step)
    return round(math.floor(float(value) / step) * step, precision)

def _ceil_to_step(value: float, step: float, precision: int = 8) -> float:
    step = float(step)
    return round(math.ceil(float(value) / step) * step, precision)

def _round_to_tick(value: float, tick: float) -> float:
    tick = float(tick)
    return round(round(value / tick) * tick, 8)

def _load_symbol_filters(symbol: str) -> dict:
    sym = str(symbol).upper()
    if sym in _SYMBOL_FILTERS_CACHE:
        return _SYMBOL_FILTERS_CACHE[sym]

    ei = futures_exchange_info_safe()
    if not isinstance(ei, dict) or "symbols" not in ei:
        raise RuntimeError("Cannot load futures exchange info (filters)")

    data = None
    for s in ei["symbols"]:
        if s.get("symbol") == sym:
            data = s
            break
    if not data:
        raise ValueError(f"Symbol {sym} not found in exchange info")

    # אתרים רלוונטיים
    price_filter = next((f for f in data["filters"] if f["filterType"] == "PRICE_FILTER"), None)
    lot_filter   = next((f for f in data["filters"] if f["filterType"] == "LOT_SIZE"), None)
    notion_filter = next((f for f in data["filters"] if f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL")), None)

    tick_size = _to_float(price_filter.get("tickSize") if price_filter else "0.0001", 0.0001)
    step_size = _to_float(lot_filter.get("stepSize") if lot_filter else "0.001", 0.001)

    # שדות משתנים בין גירסאות
    min_qty = _to_float(lot_filter.get("minQty") if lot_filter else "0.0", 0.0)
    min_notional = 0.0
    if notion_filter:
        # חלק מהסביבות משתמש MIN_NOTIONAL.notional, בחלקן NOTIONAL.minNotional
        min_notional = _to_float(
            notion_filter.get("notional", notion_filter.get("minNotional", "0.0")), 0.0
        )

    out = {
        "tickSize": tick_size,
        "stepSize": step_size,
        "minQty": min_qty,
        "minNotional": min_notional or 5.0,  # ברירת־מחדל שמרנית
    }
    _SYMBOL_FILTERS_CACHE[sym] = out
    return out

def _compute_qty(budget_usd: float, leverage: int, entry_price: float, step_size: float, min_qty: float) -> float:
    notional = float(budget_usd) * int(leverage)
    raw_qty = notional / float(entry_price)
    qty = _floor_to_step(raw_qty, step_size, precision=8)
    if qty < min_qty:
        # נסה ceil ל-step אם זה מעלה אותנו מעל המינימום
        qty = _ceil_to_step(min_qty, step_size, precision=8)
    return qty

def _ensure_notional(qty: float, price: float, min_notional: float) -> bool:
    return (float(qty) * float(price)) >= float(min_notional)

def _side_for_entry(direction: str) -> str:
    d = (direction or "").upper()
    return "BUY" if d == "LONG" else "SELL"

def _side_for_exit(direction: str) -> str:
    d = (direction or "").upper()
    return "SELL" if d == "LONG" else "BUY"

async def binance_futures_trade(
    symbol: str,
    side: str,            # "LONG" / "SHORT"
    entry: float,
    sl: float,
    tp: float,
    leverage: int = 20,
    budget: float = 100.0,
    market_type: str = "futures",
    margin_type: str = "ISOLATED",  # או "CROSSED"
) -> Dict[str, Any]:
    """
    מבצע טרייד Limit + Stop-Limit/TP-Limit בפיוצ'רס USDT-M.
    - מכין מינוף ומוד מרג'ין
    - מבצע פקודת LIMIT לכניסה (GTC)
    - מציב SL/TP כפקודות LIMIT מופעלות (STOP/TAKE_PROFIT) עם reduceOnly
    - מחזיר מזהי הזמנות ותוצאה
    """
    if market_type.lower() != "futures":
        raise ValueError("Only futures market_type is supported here.")

    symbol = str(symbol).upper()
    direction = (side or "").upper()
    entry_price = float(entry)
    stop_price = float(sl)
    take_profit = float(tp)

    # 1) פילטרים
    filters = _load_symbol_filters(symbol)
    tick = filters["tickSize"]
    step = filters["stepSize"]
    min_qty = filters["minQty"]
    min_notional = filters["minNotional"]

    # 2) התקנת מינוף ומרג'ין (לא מפיל אם נכשל)
    try:
        _retry_call(lambda: _client.futures_change_margin_type(symbol=symbol, marginType=margin_type), name="change_margin_type")
    except Exception as e:
        logging.debug(f"[trader] change_margin_type ignored: {e}")

    try:
        _retry_call(lambda: _client.futures_change_leverage(symbol=symbol, leverage=int(leverage)), name="change_leverage")
    except Exception as e:
        logging.debug(f"[trader] change_leverage ignored: {e}")

    # 3) עיגול מחירים
    entry_p = _round_to_tick(entry_price, tick)
    sl_trigger = _round_to_tick(stop_price, tick)
    tp_trigger = _round_to_tick(take_profit, tick)

    # עבור STOP/TP מסוג Limit דרוש גם price (limit) בנוסף ל-stopPrice (trigger):
    # נגדיר מחיר ל-limit כך שיהיה "גרוע" מספיק כדי להתמלא אחרי הטריגר:
    if direction == "LONG":
        sl_limit = _round_to_tick(max(sl_trigger - tick, tick), tick)          # מעט מתחת לטריגר
        tp_limit = _round_to_tick(min(tp_trigger + tick, tp_trigger * 1.002), tick)  # מעט מעל הטריגר
    else:
        sl_limit = _round_to_tick(min(sl_trigger + tick, sl_trigger * 1.002), tick)  # מעט מעל הטריגר
        tp_limit = _round_to_tick(max(tp_trigger - tick, tick), tick)          # מעט מתחת לטריגר

    # 4) כמות
    qty = _compute_qty(budget_usd=budget, leverage=int(leverage), entry_price=entry_p, step_size=step, min_qty=min_qty)
    if not _ensure_notional(qty, entry_p, min_notional):
        # נסה להעלות מעט כמות ל-step הבא כדי לפגוש notional
        qty_test = _ceil_to_step(min_notional / entry_p, step, precision=8)
        if qty_test > qty:
            qty = qty_test
    if qty < min_qty or qty <= 0:
        raise ValueError(f"Qty below minimum after rounding: qty={qty}, min_qty={min_qty}")

    # 5) צדדים
    entry_side = _side_for_entry(direction)
    exit_side = _side_for_exit(direction)

    # 6) הזמנת LIMIT לכניסה
    entry_order = _retry_call(
        lambda: _client.futures_create_order(
            symbol=symbol,
            side=entry_side,
            type="LIMIT",
            timeInForce="GTC",
            quantity=qty,
            price=entry_p,
            reduceOnly=False
        ),
        name="entry_LIMIT"
    )
    if not isinstance(entry_order, dict) or "orderId" not in entry_order:
        raise RuntimeError(f"Failed to place entry order: {entry_order}")

    # 7) הזמנות SL/TP כ-Stop-Limit עם reduceOnly
    # SL
    sl_order = _retry_call(
        lambda: _client.futures_create_order(
            symbol=symbol,
            side=exit_side,
            type="STOP",
            timeInForce="GTC",
            quantity=qty,
            stopPrice=sl_trigger,   # trigger
            price=sl_limit,         # limit
            reduceOnly=True,
            workingType="CONTRACT_PRICE"  # אפשר גם MARK_PRICE; CONTRACT=last
        ),
        name="stop_limit"
    )
    if not isinstance(sl_order, dict) or "orderId" not in sl_order:
        # אם נכשל — ננסה ליצור STOP_MARKET closePosition (כמעט תמיד מותר), אך ביקשת LIMIT בלבד.
        # אז במקום fallback ל-MARKET, נתריע ונחזיר עם error כדי לא לשבור את המדיניות.
        raise RuntimeError(f"Failed to place STOP-LIMIT order: {sl_order}")

    # TP
    tp_order = _retry_call(
        lambda: _client.futures_create_order(
            symbol=symbol,
            side=exit_side,
            type="TAKE_PROFIT",
            timeInForce="GTC",
            quantity=qty,
            stopPrice=tp_trigger,   # trigger
            price=tp_limit,         # limit
            reduceOnly=True,
            workingType="CONTRACT_PRICE"
        ),
        name="tp_limit"
    )
    if not isinstance(tp_order, dict) or "orderId" not in tp_order:
        raise RuntimeError(f"Failed to place TP-LIMIT order: {tp_order}")

    return {
        "ok": True,
        "symbol": symbol,
        "direction": direction,
        "leverage": int(leverage),
        "qty": float(qty),
        "entry": {"price": entry_p, "orderId": entry_order["orderId"], "clientOrderId": entry_order.get("clientOrderId")},
        "sl":    {"trigger": sl_trigger, "limit": sl_limit, "orderId": sl_order["orderId"]},
        "tp":    {"trigger": tp_trigger, "limit": tp_limit, "orderId": tp_order["orderId"]},
    }
















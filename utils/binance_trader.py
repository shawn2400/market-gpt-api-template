# utils/binance_trader.py
import math
import logging
from typing import Dict, Any

from utils.binance_client import get_client, futures_exchange_info_safe, retry_call
from utils import config

_client = get_client()

# Cache לפילטרים לכל סימבול
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

    meta = None
    for s in ei["symbols"]:
        if s.get("symbol") == sym:
            meta = s
            break
    if not meta:
        raise ValueError(f"Symbol {sym} not found in exchange info")

    price_filter = next((f for f in meta["filters"] if f["filterType"] == "PRICE_FILTER"), None)
    lot_filter   = next((f for f in meta["filters"] if f["filterType"] == "LOT_SIZE"), None)
    notion_filter = next((f for f in meta["filters"] if f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL")), None)

    tick_size = _to_float(price_filter.get("tickSize") if price_filter else "0.0001", 0.0001)
    step_size = _to_float(lot_filter.get("stepSize") if lot_filter else "0.001", 0.001)
    min_qty = _to_float(lot_filter.get("minQty") if lot_filter else "0.0", 0.0)
    min_notional = 0.0
    if notion_filter:
        min_notional = _to_float(notion_filter.get("notional", notion_filter.get("minNotional", "0.0")), 0.0)

    out = {
        "tickSize": tick_size,
        "stepSize": step_size,
        "minQty": min_qty,
        "minNotional": min_notional or 5.0,  # דיפולט שמרני
    }
    _SYMBOL_FILTERS_CACHE[sym] = out
    return out

def _compute_qty(budget_usd: float, leverage: int, entry_price: float, step_size: float, min_qty: float) -> float:
    notional = float(budget_usd) * int(leverage)
    raw_qty = notional / float(entry_price)
    qty = _floor_to_step(raw_qty, step_size, precision=8)
    if qty < min_qty:
        qty = _ceil_to_step(min_qty, step_size, precision=8)
    return qty

def _ensure_notional(qty: float, price: float, min_notional: float) -> bool:
    return (float(qty) * float(price)) >= float(min_notional)

def _side_for_entry(direction: str) -> str:
    return "BUY" if (direction or "").upper() == "LONG" else "SELL"

def _side_for_exit(direction: str) -> str:
    return "SELL" if (direction or "").upper() == "LONG" else "BUY"

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
    ביצוע טרייד USDT-M Futures:
      - כניסה LIMIT (GTC) בלבד
      - SL/TP כ-STOP/TAKE_PROFIT (Limit) עם reduceOnly
      - עיגול לפי tick/step, בדיקות minQty/minNotional
    """
    if market_type.lower() != "futures":
        raise ValueError("Only futures market_type is supported.")

    symbol = str(symbol).upper()
    direction = (side or "").upper()
    entry_price = float(entry)
    stop_price = float(sl)
    take_profit = float(tp)

    # פילטרים
    filters = _load_symbol_filters(symbol)
    tick = filters["tickSize"]
    step = filters["stepSize"]
    min_qty = filters["minQty"]
    min_notional = filters["minNotional"]

    # מינוף/מצב מרג'ין (לא מפיל אם נכשל)
    try:
        retry_call(lambda: _client.futures_change_margin_type(symbol=symbol, marginType=margin_type), name="change_margin_type")
    except Exception as e:
        logging.debug(f"[trader] change_margin_type ignored: {e}")
    try:
        retry_call(lambda: _client.futures_change_leverage(symbol=symbol, leverage=int(leverage)), name="change_leverage")
    except Exception as e:
        logging.debug(f"[trader] change_leverage ignored: {e}")

    # עיגול מחירים
    entry_p = _round_to_tick(entry_price, tick)
    sl_trigger = _round_to_tick(stop_price, tick)
    tp_trigger = _round_to_tick(take_profit, tick)

    # מחירי limit עבור ה-STOP/TP (שיתמלאו אחרי הטריגר)
    if direction == "LONG":
        sl_limit = _round_to_tick(max(sl_trigger - tick, tick), tick)
        tp_limit = _round_to_tick(min(tp_trigger + tick, tp_trigger * 1.002), tick)
    else:
        sl_limit = _round_to_tick(min(sl_trigger + tick, sl_trigger * 1.002), tick)
        tp_limit = _round_to_tick(max(tp_trigger - tick, tick), tick)

    # כמות
    qty = _compute_qty(budget_usd=budget, leverage=int(leverage), entry_price=entry_p, step_size=step, min_qty=min_qty)
    if not _ensure_notional(qty, entry_p, min_notional):
        qty2 = _ceil_to_step(min_notional / entry_p, step, precision=8)
        if qty2 > qty:
            qty = qty2
    if qty < min_qty or qty <= 0:
        raise ValueError(f"Qty below minimum after rounding: qty={qty}, min_qty={min_qty}")

    entry_side = _side_for_entry(direction)
    exit_side = _side_for_exit(direction)

    # LIMIT כניסה
    entry_order = retry_call(
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

    # STOP-LIMIT (SL)
    sl_order = retry_call(
        lambda: _client.futures_create_order(
            symbol=symbol,
            side=exit_side,
            type="STOP",
            timeInForce="GTC",
            quantity=qty,
            stopPrice=sl_trigger,
            price=sl_limit,
            reduceOnly=True,
            workingType="CONTRACT_PRICE"
        ),
        name="stop_limit"
    )
    if not isinstance(sl_order, dict) or "orderId" not in sl_order:
        raise RuntimeError(f"Failed to place STOP-LIMIT order: {sl_order}")

    # TAKE_PROFIT-LIMIT (TP)
    tp_order = retry_call(
        lambda: _client.futures_create_order(
            symbol=symbol,
            side=exit_side,
            type="TAKE_PROFIT",
            timeInForce="GTC",
            quantity=qty,
            stopPrice=tp_trigger,
            price=tp_limit,
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

















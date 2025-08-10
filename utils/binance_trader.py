# utils/binance_trader.py
import os
import math
import asyncio
import logging
from decimal import Decimal, ROUND_DOWN, getcontext
from typing import Optional, Dict, Any, Tuple

from utils import config
from utils.binance_client import get_client, retry_call, futures_exchange_info_safe

SKIP_MUTATIONS = (str(getattr(config, "BINANCE_SKIP_ACCOUNT_MUTATIONS",
                              os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "true"))).lower() == "true")
FORCE_HEDGE   = (str(getattr(config, "BINANCE_FORCE_HEDGE_MODE",
                              os.getenv("BINANCE_FORCE_HEDGE_MODE", "false"))).lower() == "true")
MAX_LEVERAGE  = int(getattr(config, "MAX_LEVERAGE", os.getenv("MAX_LEVERAGE", "35")))

# דיוק גבוה מספיק לרוב ה־tick/step בבינאנס
getcontext().prec = 28

# ---------- Helpers: exchangeInfo / filters / precision ----------
def _find_symbol_info(exchange_info: Dict[str, Any], symbol: str) -> Optional[Dict[str, Any]]:
    if not exchange_info or "symbols" not in exchange_info:
        return None
    su = symbol.upper()
    for s in exchange_info["symbols"]:
        if s.get("symbol") == su:
            return s
    return None

def _get_filters(sym_info: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for f in sym_info.get("filters", []):
        out[f.get("filterType")] = f
    return out

def _decimal_step_round(value: float, step: float) -> Decimal:
    """עיגול מטה לפי step באמצעות Decimal כדי להימנע משגיאות float."""
    if step <= 0:
        return Decimal(str(value))
    v = Decimal(str(value))
    s = Decimal(str(step))
    # floor ל־step
    return (v // s) * s

def _fmt_decimal(x: Decimal, precision: Optional[int]) -> str:
    if precision is None or precision < 0:
        # חיתוך עד 10 ספרות אחרי הנקודה כברירת מחדל
        return format(x.quantize(Decimal("0.0000000001"), rounding=ROUND_DOWN).normalize(), 'f')
    q = Decimal(1).scaleb(-precision)  # 10^-precision
    return format(x.quantize(q, rounding=ROUND_DOWN).normalize(), 'f')

def _apply_price_tick(price: float, tick: float, price_precision: Optional[int]) -> Tuple[Decimal, str]:
    dec = _decimal_step_round(price, tick)
    return dec, _fmt_decimal(dec, price_precision)

def _apply_qty_step(qty: float, step: float, qty_precision: Optional[int]) -> Tuple[Decimal, str]:
    dec = _decimal_step_round(qty, step)
    return dec, _fmt_decimal(dec, qty_precision)

# ---------- Account setup (hedge / leverage) ----------
def _ensure_position_mode(client, hedge: bool) -> bool:
    try:
        info = retry_call(lambda: client.futures_get_position_mode(), "futures_get_position_mode")
        if not isinstance(info, dict) or "dualSidePosition" not in info:
            logging.warning("[TRADER] could not read position mode; response=%s", info)
            return False
        cur = bool(info["dualSidePosition"])
        if cur != hedge:
            if SKIP_MUTATIONS:
                logging.warning("[TRADER] hedge mode mismatch (cur=%s, want=%s) אך Mutations מושבת — מדלגים.", cur, hedge)
                return False
            resp = retry_call(lambda: client.futures_change_position_mode(dualSidePosition=hedge),
                              "futures_change_position_mode")
            logging.info("[TRADER] position_mode set -> hedge=%s | resp=%s", hedge, resp)
        return True
    except Exception as e:
        logging.error("[TRADER] ensure hedge mode failed: %s", e)
        return False

def _set_leverage(client, symbol: str, leverage: int) -> bool:
    lev = max(1, min(int(leverage), MAX_LEVERAGE))
    try:
        if SKIP_MUTATIONS:
            logging.warning("[TRADER] leverage set skipped (Mutations disabled). requested=%s", lev)
            return False
        resp = retry_call(lambda: client.futures_change_leverage(symbol=symbol.upper(), leverage=lev),
                          f"change_leverage({symbol})")
        logging.info("[TRADER] leverage set %s -> %s", symbol, resp)
        return True
    except Exception as e:
        logging.error("[TRADER] set leverage failed: %s", e)
        return False

# ---------- Order builders ----------
def _exit_side_for(direction: str) -> str:
    return "SELL" if direction == "LONG" else "BUY"

def _place_limit_entry(client, symbol: str, side: str, price_s: str, qty_s: str, position_side: Optional[str]) -> Dict[str, Any]:
    params = dict(
        symbol=symbol.upper(),
        side=("BUY" if side == "LONG" else "SELL"),
        type="LIMIT",
        timeInForce="GTC",
        price=price_s,
        quantity=qty_s,
        newOrderRespType="RESULT",
        reduceOnly=False,
    )
    if position_side:
        params["positionSide"] = position_side
    return retry_call(lambda: client.futures_create_order(**params), f"entry_LIMIT({symbol})")

def _place_stop_like(client, symbol: str, direction: str, stop_price_s: str, limit_price_s: str,
                     qty_s: str, kind: str, position_side: Optional[str]) -> Dict[str, Any]:
    """
    kind: 'STOP' (SL) או 'TAKE_PROFIT' (TP) — הזמנות LIMIT (לא מרקט) עם stopPrice+price.
    יציאה תמיד בכיוון ההפוך לכניסה; reduceOnly=True.
    """
    params = dict(
        symbol=symbol.upper(),
        side=_exit_side_for(direction),
        type=kind,                  # "STOP" / "TAKE_PROFIT"
        timeInForce="GTC",
        stopPrice=stop_price_s,
        price=limit_price_s,
        quantity=qty_s,
        workingType="MARK_PRICE",   # שיקול: MARK_PRICE יציב מול מניפולציות; אפשר לשנות ל-CONTRACT_PRICE
        priceProtect=True,
        reduceOnly=True,
        newOrderRespType="RESULT",
    )
    if position_side:
        params["positionSide"] = position_side
    return retry_call(lambda: client.futures_create_order(**params), f"{kind}_LIMIT({symbol})")

# ---------- Public: main trade flow ----------
async def binance_futures_trade(
    symbol: str,
    side: str,                 # 'LONG' or 'SHORT'
    entry: float,
    sl: float,
    tp: float,
    leverage: int,
    budget: float,
    quantity: Optional[float] = None,
    market_type: str = "futures",
) -> Dict[str, Any]:
    """
    מבצע:
      1) ולידציה וטעינת מידע סימבול (tick/lot/precision).
      2) Hedge mode (אופציונלי) + Leverage.
      3) Limit Entry + STOP (SL) + TAKE_PROFIT (TP) — reduceOnly, לא Market.
    """
    if market_type.lower() != "futures":
        raise ValueError("Only futures is supported in this trader")

    if SKIP_MUTATIONS:
        raise RuntimeError("BINANCE_SKIP_ACCOUNT_MUTATIONS=true — כתיבה מושבתת עד אישור IP ב-Binance.")

    client = get_client()

    # 1) exchangeInfo + filters
    ex_info = await asyncio.to_thread(futures_exchange_info_safe)
    sym_info = _find_symbol_info(ex_info, symbol)
    if not sym_info:
        raise RuntimeError(f"symbol {symbol} not found in futures_exchange_info")

    filters = _get_filters(sym_info)
    price_filter = filters.get("PRICE_FILTER", {}) or {}
    lot_filter   = filters.get("LOT_SIZE", {}) or {}
    min_notional = float(filters.get("MIN_NOTIONAL", {}).get("notional", 0) or 0.0)

    tick_size = float(price_filter.get("tickSize", "0.01"))
    step_size = float(lot_filter.get("stepSize", "0.001"))
    min_qty   = float(lot_filter.get("minQty", "0.0"))

    # precision אופציונלי (לא תמיד קיים ב-futures)
    price_precision = sym_info.get("pricePrecision")
    qty_precision   = sym_info.get("quantityPrecision")

    # מחירים מעוגלים ל-tick
    entry_dec, entry_s = _apply_price_tick(float(entry), tick_size, price_precision)
    sl_dec,    sl_s    = _apply_price_tick(float(sl),    tick_size, price_precision)
    tp_dec,    tp_s    = _apply_price_tick(float(tp),    tick_size, price_precision)

    if entry_dec <= 0:
        raise RuntimeError("invalid entry price after rounding")

    # 2) חישוב כמות
    if quantity is None:
        raw_qty = Decimal(str(budget)) / entry_dec
    else:
        raw_qty = Decimal(str(quantity))

    qty_dec = _decimal_step_round(float(raw_qty), step_size)
    # שמירה על minQty
    if qty_dec < Decimal(str(min_qty)):
        raise RuntimeError(f"quantity too small after rounding: {qty_dec} < minQty {min_qty}")

    qty_s = _fmt_decimal(qty_dec, qty_precision)
    notional = float(qty_dec * entry_dec)

    if min_notional and notional < min_notional:
        logging.warning("[TRADER] notional too small: qty*entry=%.6f < minNotional=%.6f", notional, min_notional)

    # 3) Hedge + Leverage
    position_side = None
    if FORCE_HEDGE:
        ok = await asyncio.to_thread(_ensure_position_mode, client, True)
        position_side = ("LONG" if side.upper() == "LONG" else "SHORT") if ok else None
    await asyncio.to_thread(_set_leverage, client, symbol, leverage)

    # 4) הזמנות
    entry_resp = await asyncio.to_thread(_place_limit_entry, client, symbol, side.upper(), entry_s, qty_s, position_side)
    if not entry_resp or not isinstance(entry_resp, dict) or "orderId" not in entry_resp:
        raise RuntimeError(f"Failed to place entry LIMIT: {entry_resp}")

    # יציאות: תמיד ההפך מכיוון הכניסה
    sl_resp = await asyncio.to_thread(_place_stop_like, client, symbol, side.upper(),
                                      stop_price_s=sl_s, limit_price_s=sl_s, qty_s=qty_s,
                                      kind="STOP", position_side=position_side)
    if not sl_resp or not isinstance(sl_resp, dict) or "orderId" not in sl_resp:
        raise RuntimeError(f"Failed to place STOP (SL): {sl_resp}")

    tp_resp = await asyncio.to_thread(_place_stop_like, client, symbol, side.upper(),
                                      stop_price_s=tp_s, limit_price_s=tp_s, qty_s=qty_s,
                                      kind="TAKE_PROFIT", position_side=position_side)
    if not tp_resp or not isinstance(tp_resp, dict) or "orderId" not in tp_resp:
        raise RuntimeError(f"Failed to place TAKE_PROFIT (TP): {tp_resp}")

    result = {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "entry": float(entry_dec),
        "qty": float(qty_dec),
        "sl": float(sl_dec),
        "tp": float(tp_dec),
        "leverage": int(leverage),
        "positionSide": position_side,
        "orders": {
            "entry": entry_resp,
            "sl": sl_resp,
            "tp": tp_resp,
        },
        "notional": notional,
        "tickSize": tick_size,
        "stepSize": step_size,
        "minQty": min_qty,
        "minNotional": min_notional,
    }
    return result






















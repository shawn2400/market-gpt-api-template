# utils/binance_trader.py
import os
import math
import asyncio
import logging
from typing import Optional, Dict, Any

from utils import config
from utils.binance_client import get_client, retry_call, futures_exchange_info_safe

SKIP_MUTATIONS = (str(getattr(config, "BINANCE_SKIP_ACCOUNT_MUTATIONS", os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "true"))).lower() == "true")
FORCE_HEDGE = (str(getattr(config, "BINANCE_FORCE_HEDGE_MODE", os.getenv("BINANCE_FORCE_HEDGE_MODE", "false"))).lower() == "true")
MAX_LEVERAGE = int(getattr(config, "MAX_LEVERAGE", os.getenv("MAX_LEVERAGE", "35")))

# ---------- Helpers: filters / rounding ----------

def _find_symbol_info(exchange_info: Dict[str, Any], symbol: str) -> Optional[Dict[str, Any]]:
    if not exchange_info or "symbols" not in exchange_info:
        return None
    for s in exchange_info["symbols"]:
        if s.get("symbol") == symbol.upper():
            return s
    return None

def _get_filters(sym_info: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for f in sym_info.get("filters", []):
        out[f.get("filterType")] = f
    return out

def _step_round(value: float, step: float) -> float:
    if step <= 0:
        return value
    # לנקב לרמה המדויקת של ה-step
    return math.floor(value / step) * step

def _price_round(price: float, tick_size: float) -> float:
    return float(f"{_step_round(price, tick_size):.10f}")

def _qty_round(qty: float, step_size: float) -> float:
    return float(f"{_step_round(qty, step_size):.10f}")

# ---------- Account setup (hedge / leverage) ----------

def _ensure_position_mode(client, hedge: bool) -> bool:
    try:
        info = retry_call(lambda: client.futures_get_position_mode(), "futures_get_position_mode")
        if isinstance(info, dict) and "dualSidePosition" in info:
            cur = bool(info["dualSidePosition"])
            if cur != hedge:
                if SKIP_MUTATIONS:
                    logging.warning("[TRADER] hedge mode mismatch (cur=%s, want=%s) אך Mutations מושבת — מדלגים.", cur, hedge)
                    return False
                resp = retry_call(lambda: client.futures_change_position_mode(dualSidePosition=hedge), "futures_change_position_mode")
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
        resp = retry_call(lambda: client.futures_change_leverage(symbol=symbol, leverage=lev), f"change_leverage({symbol})")
        logging.info("[TRADER] leverage set %s -> %s", symbol, resp)
        return True
    except Exception as e:
        logging.error("[TRADER] set leverage failed: %s", e)
        return False

# ---------- Order placement ----------

def _place_limit_entry(client, symbol: str, side: str, price: float, qty: float, position_side: Optional[str]) -> Dict[str, Any]:
    params = dict(
        symbol=symbol,
        side=("BUY" if side == "LONG" else "SELL"),
        type="LIMIT",
        timeInForce="GTC",
        price=f"{price:.10f}",
        quantity=f"{qty:.10f}",
    )
    if position_side:
        params["positionSide"] = position_side
    return retry_call(lambda: client.futures_create_order(**params), f"entry_LIMIT({symbol})")

def _place_stop_limit(client, symbol: str, side: str, stop_price: float, limit_price: float, qty: float, kind: str, position_side: Optional[str]) -> Dict[str, Any]:
    """
    kind: 'STOP' (SL) או 'TAKE_PROFIT' (TP)
    """
    params = dict(
        symbol=symbol,
        side=("SELL" if side == "LONG" else "BUY") if kind == "STOP" else ("BUY" if side == "LONG" else "SELL"),
        type=kind,                  # STOP / TAKE_PROFIT (לא מרקט)
        timeInForce="GTC",
        stopPrice=f"{stop_price:.10f}",
        price=f"{limit_price:.10f}",
        quantity=f"{qty:.10f}",
        workingType="MARK_PRICE",   # עדין מאפשר הגנות; אם תרצה LAST_PRICE שנה כאן
        priceProtect=True,
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
    1) ולידציה וטעינת מידע סימבול (tick/lot).
    2) hedge mode (אופציונלי) + leverage.
    3) Limit Entry + STOP (SL) + TAKE_PROFIT (TP) – לא Market.
    הכל עם עיגול לפי פילטרי הבורסה.
    """
    if market_type.lower() != "futures":
        raise ValueError("Only futures is supported in this trader")

    if SKIP_MUTATIONS:
        raise RuntimeError("BINANCE_SKIP_ACCOUNT_MUTATIONS=true — כתיבה מושבתת עד אישור IP ב-Binance.")

    client = get_client()

    # שלב 1: info + פילטרים
    ex_info = await asyncio.to_thread(futures_exchange_info_safe)
    sym_info = _find_symbol_info(ex_info, symbol)
    if not sym_info:
        raise RuntimeError(f"symbol {symbol} not found in futures_exchange_info")

    filters = _get_filters(sym_info)
    price_filter = filters.get("PRICE_FILTER", {})
    lot_filter = filters.get("LOT_SIZE", {})
    min_notional = float(filters.get("MIN_NOTIONAL", {}).get("notional", 0) or 0)

    tick = float(price_filter.get("tickSize", "0.01"))
    step = float(lot_filter.get("stepSize", "0.001"))
    min_qty = float(lot_filter.get("minQty", "0.0"))

    entry = _price_round(float(entry), tick)
    sl    = _price_round(float(sl), tick)
    tp    = _price_round(float(tp), tick)

    # כמות
    if quantity is None:
        if entry <= 0:
            raise RuntimeError("invalid entry price")
        raw_qty = float(budget) / float(entry)
        qty = _qty_round(raw_qty, step)
    else:
        qty = _qty_round(float(quantity), step)

    if qty < max(min_qty, 0.0):
        raise RuntimeError(f"quantity too small after rounding: {qty} < minQty {min_qty}")

    if (qty * entry) < min_notional:
        logging.warning("[TRADER] notional too small: qty*entry=%.6f < minNotional=%.6f", qty * entry, min_notional)

    # שלב 2: hedge/leverage
    position_side = None
    if FORCE_HEDGE:
        ok = await asyncio.to_thread(_ensure_position_mode, client, True)
        position_side = ("LONG" if side == "LONG" else "SHORT") if ok else None
    await asyncio.to_thread(_set_leverage, client, symbol, leverage)

    # שלב 3: יצירת פקודות
    # Entry: LIMIT
    entry_resp = await asyncio.to_thread(_place_limit_entry, client, symbol, side, entry, qty, position_side)
    if not entry_resp or (isinstance(entry_resp, dict) and entry_resp.get("status") == "EXPIRED"):
        raise RuntimeError(f"Failed to place entry LIMIT: {entry_resp}")

    # SL/TP: STOP / TAKE_PROFIT (לא מרקט)
    if side == "LONG":
        sl_resp = await asyncio.to_thread(_place_stop_limit, client, symbol, side, stop_price=sl,   limit_price=sl, qty=qty, kind="STOP",         position_side=position_side)
        tp_resp = await asyncio.to_thread(_place_stop_limit, client, symbol, side, stop_price=tp,   limit_price=tp, qty=qty, kind="TAKE_PROFIT",  position_side=position_side)
    else:
        sl_resp = await asyncio.to_thread(_place_stop_limit, client, symbol, side, stop_price=sl,   limit_price=sl, qty=qty, kind="STOP",         position_side=position_side)
        tp_resp = await asyncio.to_thread(_place_stop_limit, client, symbol, side, stop_price=tp,   limit_price=tp, qty=qty, kind="TAKE_PROFIT",  position_side=position_side)

    result = {
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "qty": qty,
        "sl": sl,
        "tp": tp,
        "leverage": int(leverage),
        "positionSide": position_side,
        "orders": {
            "entry": entry_resp,
            "sl": sl_resp,
            "tp": tp_resp,
        }
    }
    return result





















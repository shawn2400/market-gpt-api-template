# utils/binance_trader.py (with Fail-Safe Cancel)
import os
import asyncio
import logging
from decimal import Decimal, ROUND_DOWN, getcontext
from typing import Optional, Dict, Any, Tuple, Literal

from utils import config
from utils.binance_client import get_client, retry_call, futures_exchange_info_safe

EXECUTE_TRADES = bool(getattr(config, "EXECUTE_TRADES", False))
BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV = str(
    getattr(config, "BINANCE_SKIP_ACCOUNT_MUTATIONS",
            os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "true"))
).lower() in ("1", "true", "yes", "y", "on")
SKIP_MUTATIONS = (not EXECUTE_TRADES) or BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV

FORCE_HEDGE   = (str(getattr(config, "BINANCE_FORCE_HEDGE_MODE",
                              os.getenv("BINANCE_FORCE_HEDGE_MODE", "false"))).lower() == "true")
MAX_LEVERAGE  = int(getattr(config, "MAX_LEVERAGE", os.getenv("MAX_LEVERAGE", "35")))

getcontext().prec = 28
log = logging.getLogger(__name__)

MarginLiteral = Literal["ISOLATED", "CROSSED"]

# ------------------------------------------------------------
# Safety helper: cancel all orders for a symbol
# ------------------------------------------------------------
def _cancel_all_orders(client, symbol: str) -> None:
    try:
        resp = retry_call(lambda: client.futures_cancel_all_open_orders(symbol=symbol.upper()),
                          f"cancel_all_orders({symbol})")
        logging.warning(f"[TRADER] All open orders for {symbol} canceled: {resp}")
    except Exception as e:
        logging.error(f"[TRADER] cancel_all_orders failed for {symbol}: {e}")

# ... כל הפונקציות העזר שלך (כמו קודם) ...

# ------------------------------------------------------------
# Public entry with Fail-Safe
# ------------------------------------------------------------
async def binance_futures_trade(
    symbol: str,
    side: str,
    entry: float,
    sl: float,
    tp: float,
    leverage: int,
    budget: float,
    quantity: Optional[float] = None,
    market_type: str = "futures",
    cid_prefix: str = "algogpt",
    margin_type: MarginLiteral = "ISOLATED",
) -> Dict[str, Any]:
    if market_type.lower() != "futures":
        raise ValueError("Only futures is supported in this trader")

    if SKIP_MUTATIONS:
        raise RuntimeError("Mutations disabled (EXECUTE_TRADES=false or BINANCE_SKIP_ACCOUNT_MUTATIONS=true).")

    side = side.upper()
    if side not in ("LONG", "SHORT"):
        raise RuntimeError(f"invalid side: {side}")

    want_margin = margin_type.upper()
    if want_margin not in ("ISOLATED", "CROSSED"):
        raise RuntimeError(f"invalid margin_type: {margin_type}")

    lev = max(1, min(int(leverage), MAX_LEVERAGE))
    client = get_client()

    # ---- Exchange Info / Filters ----
    ex_info = await asyncio.to_thread(futures_exchange_info_safe)
    sym_info = _find_symbol_info(ex_info, symbol)
    if not sym_info:
        raise RuntimeError(f"symbol {symbol} not found in futures_exchange_info")

    filters = _get_filters(sym_info)
    price_filter = filters.get("PRICE_FILTER", {}) or {}
    lot_filter   = filters.get("LOT_SIZE", {}) or {}
    min_notional = Decimal(str(filters.get("MIN_NOTIONAL", {}).get("notional", 0) or 0.0))

    tick_size = Decimal(str(price_filter.get("tickSize", "0.01")))
    step_size = Decimal(str(lot_filter.get("stepSize", "0.001")))
    min_qty   = Decimal(str(lot_filter.get("minQty", "0.0")))

    price_precision = sym_info.get("pricePrecision")
    qty_precision   = sym_info.get("quantityPrecision")

    # ---- Round ----
    entry_dec, entry_s = _apply_price_tick(float(entry), float(tick_size), price_precision)
    sl_dec,    sl_s    = _apply_price_tick(float(sl),    float(tick_size), price_precision)
    tp_dec,    tp_s    = _apply_price_tick(float(tp),    float(tick_size), price_precision)

    # ---- Quantity ----
    if quantity is None:
        raw_qty = (Decimal(str(budget)) * Decimal(str(lev))) / entry_dec
    else:
        raw_qty = Decimal(str(quantity))
    qty_dec, qty_s = _apply_qty_step(raw_qty, float(step_size), qty_precision)

    # ---- Safety Checks ----
    if qty_dec < min_qty or qty_dec <= 0:
        raise RuntimeError("Quantity too small")
    notional = (qty_dec * entry_dec)
    if min_notional and notional < min_notional:
        raise RuntimeError("Notional too small")

    # ---- Margin + Leverage ----
    await asyncio.to_thread(_ensure_margin_type, client, symbol, want_margin)
    await asyncio.to_thread(_set_leverage, client, symbol, lev)

    # ---- Order IDs ----
    base_cid = f"{cid_prefix}:{symbol.upper()}:{side}:{int(entry_dec*1000)}:{want_margin}"
    entry_cid = f"{base_cid}:E"
    sl_cid    = f"{base_cid}:SL"
    tp_cid    = f"{base_cid}:TP"

    # ---- Place Orders with Fail-Safe ----
    try:
        entry_resp = await asyncio.to_thread(
            _place_limit_entry, client, symbol, side, entry_s, qty_s, None, entry_cid
        )
        if not entry_resp or "orderId" not in entry_resp:
            raise RuntimeError("Entry order failed")

        sl_resp = await asyncio.to_thread(
            _place_stop_like, client, symbol, side, sl_s, sl_s, qty_s, "STOP", None, sl_cid
        )
        if not sl_resp or "orderId" not in sl_resp:
            raise RuntimeError("StopLoss order failed")

        tp_resp = await asyncio.to_thread(
            _place_stop_like, client, symbol, side, tp_s, tp_s, qty_s, "TAKE_PROFIT", None, tp_cid
        )
        if not tp_resp or "orderId" not in tp_resp:
            raise RuntimeError("TakeProfit order failed")

    except Exception as e:
        # ❌ Fail-Safe: cancel all orders if something went wrong
        _cancel_all_orders(client, symbol)
        raise RuntimeError(f"Trade setup failed: {e}")

    return {
        "symbol": symbol.upper(),
        "side": side,
        "entry": float(entry_dec),
        "qty": float(qty_dec),
        "sl": float(sl_dec),
        "tp": float(tp_dec),
        "leverage": int(lev),
        "marginType": want_margin,
        "orders": {"entry": entry_resp, "sl": sl_resp, "tp": tp_resp},
    }






























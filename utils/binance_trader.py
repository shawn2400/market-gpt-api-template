# utils/binance_trader.py
import os
import asyncio
import logging
from decimal import Decimal, ROUND_DOWN, getcontext
from typing import Optional, Dict, Any, Tuple

from utils import config
from utils.binance_client import get_client, retry_call, futures_exchange_info_safe

# ----- Flags -----
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

# ----- Helpers -----
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

def _decimal_step_round(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value // step) * step  # floor to step

def _fmt_decimal(x: Decimal, precision: Optional[int]) -> str:
    if precision is None or precision < 0:
        q = Decimal("0.0000000001")
    else:
        q = Decimal(1).scaleb(-precision)
    return format(x.quantize(q, rounding=ROUND_DOWN).normalize(), 'f')

def _apply_price_tick(price: float, tick: float, price_precision: Optional[int]) -> Tuple[Decimal, str]:
    v = Decimal(str(price))
    t = Decimal(str(tick)) if tick else Decimal("0")
    dec = _decimal_step_round(v, t) if t > 0 else v
    return dec, _fmt_decimal(dec, price_precision)

def _apply_qty_step(qty: Decimal, step: float, qty_precision: Optional[int]) -> Tuple[Decimal, str]:
    s = Decimal(str(step)) if step else Decimal("0")
    dec = _decimal_step_round(qty, s) if s > 0 else qty
    return dec, _fmt_decimal(dec, qty_precision)

def _read_position_mode(client) -> Optional[bool]:
    try:
        info = retry_call(lambda: client.futures_get_position_mode(), "futures_get_position_mode")
        if isinstance(info, dict) and "dualSidePosition" in info:
            return bool(info["dualSidePosition"])
    except Exception as e:
        logging.warning(f"[TRADER] read position mode failed: {e}")
    return None

def _ensure_position_mode(client, hedge: bool) -> bool:
    try:
        cur = _read_position_mode(client)
        if cur is None:
            return False
        if cur != hedge:
            if SKIP_MUTATIONS:
                logging.warning("[TRADER] hedge mode mismatch (cur=%s, want=%s) but mutations disabled.", cur, hedge)
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
            logging.warning("[TRADER] leverage set skipped (mutations disabled). requested=%s", lev)
            return False
        resp = retry_call(lambda: client.futures_change_leverage(symbol=symbol.upper(), leverage=lev),
                          f"change_leverage({symbol})")
        logging.info("[TRADER] leverage set %s -> %s", symbol, resp)
        return True
    except Exception as e:
        logging.error("[TRADER] set leverage failed: %s", e)
        return False

def _exit_side_for(direction: str) -> str:
    return "SELL" if direction == "LONG" else "BUY"

def _place_limit_entry(client, symbol: str, side: str, price_s: str, qty_s: str,
                       position_side: Optional[str], client_order_id: Optional[str]) -> Dict[str, Any]:
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
    if client_order_id:
        params["newClientOrderId"] = client_order_id
    return retry_call(lambda: client.futures_create_order(**params), f"entry_LIMIT({symbol})")

def _place_stop_like(client, symbol: str, direction: str, stop_price_s: str, limit_price_s: str,
                     qty_s: str, kind: str, position_side: Optional[str], client_order_id: Optional[str]) -> Dict[str, Any]:
    params = dict(
        symbol=symbol.upper(),
        side=_exit_side_for(direction),
        type=kind,                  # "STOP" / "TAKE_PROFIT"
        timeInForce="GTC",
        stopPrice=stop_price_s,
        price=limit_price_s,
        quantity=qty_s,
        workingType="MARK_PRICE",
        priceProtect=True,
        reduceOnly=True,
        newOrderRespType="RESULT",
    )
    if position_side:
        params["positionSide"] = position_side
    if client_order_id:
        params["newClientOrderId"] = client_order_id
    return retry_call(lambda: client.futures_create_order(**params), f"{kind}_LIMIT({symbol})")

# ----- Core trade -----
async def binance_futures_trade(
    symbol: str,
    side: str,                 # 'LONG' or 'SHORT'
    entry: float,
    sl: float,
    tp: float,
    leverage: int,
    budget: float,             # margin (USDT) allocated
    quantity: Optional[float] = None,
    market_type: str = "futures",
    cid_prefix: str = "algogpt",
) -> Dict[str, Any]:
    if market_type.lower() != "futures":
        raise ValueError("Only futures is supported in this trader")

    if SKIP_MUTATIONS:
        raise RuntimeError("Mutations disabled (EXECUTE_TRADES=false or BINANCE_SKIP_ACCOUNT_MUTATIONS=true).")

    side = side.upper()
    if side not in ("LONG", "SHORT"):
        raise RuntimeError(f"invalid side: {side}")

    # Use effective leverage consistently (clamped to MAX_LEVERAGE)
    lev = max(1, min(int(leverage), MAX_LEVERAGE))

    client = get_client()

    # Exchange info + filters
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

    # Round prices to tick
    entry_dec, entry_s = _apply_price_tick(float(entry), float(tick_size), price_precision)
    sl_dec,    sl_s    = _apply_price_tick(float(sl),    float(tick_size), price_precision)
    tp_dec,    tp_s    = _apply_price_tick(float(tp),    float(tick_size), price_precision)

    if entry_dec <= 0:
        raise RuntimeError("invalid entry price after rounding")

    # SL/TP orientation guard
    if side == "LONG":
        if sl_dec >= entry_dec:
            raise RuntimeError(f"SL must be < entry for LONG (sl={sl_dec}, entry={entry_dec})")
        if tp_dec <= entry_dec:
            raise RuntimeError(f"TP must be > entry for LONG (tp={tp_dec}, entry={entry_dec})")
    else:  # SHORT
        if sl_dec <= entry_dec:
            raise RuntimeError(f"SL must be > entry for SHORT (sl={sl_dec}, entry={entry_dec})")
        if tp_dec >= entry_dec:
            raise RuntimeError(f"TP must be < entry for SHORT (tp={tp_dec}, entry={entry_dec})")

    # --- Quantity calculation (margin-based) ---
    # qty = (budget * lev) / entry
    if quantity is None:
        raw_qty = (Decimal(str(budget)) * Decimal(str(lev))) / entry_dec
    else:
        raw_qty = Decimal(str(quantity))

    qty_dec, qty_s = _apply_qty_step(raw_qty, float(step_size), qty_precision)

    if qty_dec < min_qty or qty_dec <= 0:
        # budget_needed = (minQty * entry) / lev
        min_budget = (min_qty * entry_dec) / Decimal(str(lev))
        raise RuntimeError(
            f"quantity too small after rounding: {qty_dec} < minQty {min_qty}. "
            f"Try budget ≥ {min_budget.quantize(Decimal('0.0001'), rounding=ROUND_DOWN)} "
            f"(at leverage={lev}) or increase leverage (≤ MAX_LEVERAGE={MAX_LEVERAGE})."
        )

    # Notional check (if present)
    notional = (qty_dec * entry_dec)
    if min_notional and notional < min_notional:
        # budget_needed = min_notional / lev
        min_budget_notional = (min_notional / Decimal(str(lev)))
        raise RuntimeError(
            f"notional too small: qty*entry={notional} < minNotional={min_notional}. "
            f"Try budget ≥ {min_budget_notional.quantize(Decimal('0.0001'), rounding=ROUND_DOWN)} "
            f"(at leverage={lev})."
        )

    # ----- Position mode & leverage -----
    position_side: Optional[str] = None
    acct_is_hedge = _read_position_mode(client)
    if acct_is_hedge is True:
        position_side = "LONG" if side == "LONG" else "SHORT"
    if FORCE_HEDGE:
        ok = await asyncio.to_thread(_ensure_position_mode, client, True)
        if ok:
            position_side = "LONG" if side == "LONG" else "SHORT"

    await asyncio.to_thread(_set_leverage, client, symbol, lev)

    # ----- Place orders -----
    base_cid = f"{cid_prefix}:{symbol.upper()}:{side}:{int(entry_dec*1000)}"
    entry_cid = f"{base_cid}:E"
    sl_cid    = f"{base_cid}:SL"
    tp_cid    = f"{base_cid}:TP"

    logging.info(
        "[TRADER] %s %s | entry=%s sl=%s tp=%s | qty=%s | tick=%s step=%s minQty=%s minNotional=%s | lev=%s budget=%s notional=%s",
        symbol.upper(), side, entry_s, sl_s, tp_s, qty_s, tick_size, step_size, min_qty, min_notional, lev, budget, notional
    )

    entry_resp = await asyncio.to_thread(
        _place_limit_entry, client, symbol, side, entry_s, qty_s, position_side, entry_cid
    )
    if not entry_resp or not isinstance(entry_resp, dict) or "orderId" not in entry_resp:
        raise RuntimeError(f"Failed to place entry LIMIT: {entry_resp}")

    sl_resp = await asyncio.to_thread(
        _place_stop_like, client, symbol, side, sl_s, sl_s, qty_s, "STOP", position_side, sl_cid
    )
    if not sl_resp or not isinstance(sl_resp, dict) or "orderId" not in sl_resp:
        raise RuntimeError(f"Failed to place STOP (SL): {sl_resp}")

    tp_resp = await asyncio.to_thread(
        _place_stop_like, client, symbol, side, tp_s, tp_s, qty_s, "TAKE_PROFIT", position_side, tp_cid
    )
    if not tp_resp or not isinstance(tp_resp, dict) or "orderId" not in tp_resp:
        raise RuntimeError(f"Failed to place TAKE_PROFIT (TP): {tp_resp}")

    return {
        "symbol": symbol.upper(),
        "side": side,
        "entry": float(entry_dec),
        "qty": float(qty_dec),
        "sl": float(sl_dec),
        "tp": float(tp_dec),
        "leverage": int(lev),
        "positionSide": position_side,
        "orders": {"entry": entry_resp, "sl": sl_resp, "tp": tp_resp},
        "notional": float(notional),
        "tickSize": float(tick_size),
        "stepSize": float(step_size),
        "minQty": float(min_qty),
        "minNotional": float(min_notional),
    }

# --------------------------------------------------------------------
# Grid dry-run shim (לשמירת תאימות)
# --------------------------------------------------------------------
async def binance_grid_trade(plan: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "mode": "dry_run",
        "reason": "grid executor not implemented in this module",
        "echo_plan": plan,
    }


























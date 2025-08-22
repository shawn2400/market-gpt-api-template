# utils/binance_trader.py
import os
import logging
from decimal import Decimal, ROUND_DOWN, getcontext
from typing import Dict, Any, Literal

from utils import config
from utils.binance_client import get_client, retry_call, futures_exchange_info_safe

# =========================
# Env / Flags
# =========================
EXECUTE_TRADES = bool(getattr(config, "EXECUTE_TRADES", False))
BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV = str(
    getattr(config, "BINANCE_SKIP_ACCOUNT_MUTATIONS",
            os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "true"))
).lower() in ("1", "true", "yes", "y", "on")

SKIP_MUTATIONS = (not EXECUTE_TRADES) or BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV
FORCE_HEDGE    = (str(getattr(config, "BINANCE_FORCE_HEDGE_MODE",
                               os.getenv("BINANCE_FORCE_HEDGE_MODE", "false"))).lower() == "true")
MAX_LEVERAGE   = int(getattr(config, "MAX_LEVERAGE", os.getenv("MAX_LEVERAGE", "35")))
MAX_TRADE_BUDGET = float(getattr(config, "MAX_TRADE_BUDGET", os.getenv("MAX_TRADE_BUDGET", "100")))

getcontext().prec = 28
log = logging.getLogger(__name__)

MarginLiteral = Literal["ISOLATED", "CROSSED"]

# =========================
# Helpers
# =========================
def _round_step(value: float, step: float) -> float:
    """מתאים ערך ל-stepSize"""
    if step <= 0:
        return float(value)
    return float((Decimal(str(value)).quantize(Decimal(str(step)), rounding=ROUND_DOWN)))

def _find_symbol_info(symbol: str) -> Dict[str, Any]:
    info = futures_exchange_info_safe()
    for s in info.get("symbols", []):
        if s["symbol"].upper() == symbol.upper():
            return s
    raise ValueError(f"Symbol info not found for {symbol}")

def _calc_order_qty(symbol: str, entry: float, budget: float, leverage: int) -> float:
    """חישוב כמות (quantity) לפי תקציב ולווראג'"""
    if not entry or entry <= 0:
        raise ValueError("Invalid entry price")

    notional = budget * leverage
    qty = notional / entry

    info = _find_symbol_info(symbol)
    step = 0.01
    for f in info.get("filters", []):
        if f["filterType"] == "LOT_SIZE":
            step = float(f.get("stepSize", "0.01"))
            break
    return _round_step(qty, step)

def _cancel_all_orders(client, symbol: str) -> None:
    try:
        resp = retry_call(lambda: client.futures_cancel_all_open_orders(symbol=symbol.upper()),
                          f"cancel_all_orders({symbol})")
        logging.warning(f"[TRADER] All open orders for {symbol} canceled: {resp}")
    except Exception as e:
        logging.error(f"[TRADER] cancel_all_orders failed for {symbol}: {e}")

# =========================
# Panic Button
# =========================
def force_close_position(symbol: str) -> dict:
    client = get_client()
    try:
        positions = retry_call(
            lambda: client.futures_position_information(symbol=symbol.upper()),
            f"pos_info({symbol})"
        )
        if not positions or float(positions[0].get("positionAmt", 0)) == 0:
            return {"ok": True, "msg": f"No open position for {symbol}"}

        pos = positions[0]
        amt = float(pos["positionAmt"])
        side = "SELL" if amt > 0 else "BUY"
        qty_s = str(abs(amt))

        resp = retry_call(
            lambda: client.futures_create_order(
                symbol=symbol.upper(),
                side=side,
                type="MARKET",
                quantity=qty_s,
                reduceOnly=True,
                newOrderRespType="RESULT",
            ),
            f"force_close({symbol})"
        )
        logging.warning(f"[FORCE_CLOSE] Closed {amt} {symbol} side={side} resp={resp}")
        return {"ok": True, "resp": resp}

    except Exception as e:
        logging.error(f"[FORCE_CLOSE] failed for {symbol}: {e}")
        return {"ok": False, "error": str(e)}

# =========================
# Main trade executor
# =========================
async def binance_futures_trade(symbol: str, side: str,
                                entry: float, sl: float, tp: float,
                                leverage: int, budget: float) -> dict:
    """
    מבצע טרייד עתידי ב־Binance:
    - חישוב כמות לפי budget+leverage
    - Market Entry
    - מציב SL/TP אם אפשר
    """
    symbol = symbol.upper()
    client = get_client()

    if SKIP_MUTATIONS:
        return {
            "ok": True,
            "dry_run": True,
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "budget": budget,
            "leverage": leverage
        }

    try:
        retry_call(lambda: client.futures_change_leverage(
            symbol=symbol, leverage=int(leverage)), f"set_leverage({symbol})")

        qty = _calc_order_qty(symbol, entry, budget, leverage)
        if qty <= 0:
            raise ValueError("Quantity calculated as 0")

        _cancel_all_orders(client, symbol)

        order = retry_call(
            lambda: client.futures_create_order(
                symbol=symbol,
                side="BUY" if side.upper() == "LONG" else "SELL",
                type="MARKET",
                quantity=str(qty),
                reduceOnly=False,
                newOrderRespType="RESULT",
            ),
            f"entry({symbol})"
        )

        result = {"ok": True, "order": order}

        sl, tp = float(sl), float(tp)
        stop_orders = []
        if sl > 0:
            stop_orders.append(client.futures_create_order(
                symbol=symbol,
                side="SELL" if side.upper() == "LONG" else "BUY",
                type="STOP_MARKET",
                stopPrice=str(sl),
                quantity=str(qty),
                reduceOnly=True
            ))
        if tp > 0:
            stop_orders.append(client.futures_create_order(
                symbol=symbol,
                side="SELL" if side.upper() == "LONG" else "BUY",
                type="TAKE_PROFIT_MARKET",
                stopPrice=str(tp),
                quantity=str(qty),
                reduceOnly=True
            ))

        result["stops"] = stop_orders
        logging.info(f"[TRADE] Executed {side} {symbol} qty={qty} entry={entry} sl={sl} tp={tp}")
        return result

    except Exception as e:
        logging.error(f"[TRADE] Failed {symbol} side={side}: {e}")
        return {"ok": False, "error": str(e)}
































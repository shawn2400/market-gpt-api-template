# utils/binance_trader.py (with Fail-Safe Cancel + Force Close)
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

# ------------------------------------------------------------
# Force Close Position (Panic Button)
# ------------------------------------------------------------
def force_close_position(symbol: str) -> dict:
    """
    סוגר מיידית את כל הפוזיציות הפתוחות על סימבול מסוים (Market Order).
    שימושי כ-Fail-Safe / Panic Button.
    """
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
        if amt == 0:
            return {"ok": True, "msg": f"No open position for {symbol}"}

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

# ------------------------------------------------------------
# כאן באות כל פונקציות העזר שלך (_find_symbol_info, _apply_price_tick וכו')
# וגם הפונקציה הראשית binance_futures_trade (כמו אצלך עם Fail-Safe)
# ------------------------------------------------------------































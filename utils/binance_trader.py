# utils/binance_trader.py
import os, logging
from binance.client import Client
from binance.exceptions import BinanceAPIException
from utils.binance_client import get_client, futures_mark_price

logger = logging.getLogger("algogpt.binance.trader")

async def binance_futures_trade(symbol: str, side: str, budget: float, leverage: int = 10, dry_run: bool = False):
    """
    ביצוע טרייד ב-Binance Futures.
    אם dry_run=True → מחזיר סימולציה בלבד.
    """
    client = get_client()
    symbol = symbol.upper().strip()
    side = side.upper().strip()

    try:
        price = futures_mark_price(symbol)
        if not price:
            raise RuntimeError(f"Mark price unavailable for {symbol}")

        qty = round(budget / price, 3)  # חישוב גודל פוזיציה פשוט

        if dry_run:
            logger.info(f"[DRY RUN] {side} {symbol} budget={budget} qty={qty} lev={leverage}")
            return {
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "entry": price,
                "leverage": leverage
            }

        # קביעת מינוף
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        # פתיחת פוזיציה
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=qty
        )

        entry_price = float(order["avgPrice"]) if "avgPrice" in order else price

        return {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry": entry_price,
            "leverage": leverage
        }

    except BinanceAPIException as e:
        logger.error(f"[Binance] Trade failed: {e}")
        raise RuntimeError(f"Binance API error: {e}")
    except Exception as e:
        logger.error(f"[Binance] Unexpected trade error: {e}")
        raise
































# utils/binance_trader.py
import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException
from utils.binance_client import get_client, futures_mark_price

logger = logging.getLogger("algogpt.binance.trader")

async def binance_futures_trade(
    symbol: str,
    side: str,
    budget: float,
    leverage: int = 10,
    dry_run: bool = False
):
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

        entry_price = float(order.get("avgPrice") or price)

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
        raise RuntimeError(f"Unexpected error: {e}")


def force_close_position(symbol: str) -> dict:
    """
    סוגר בכוח פוזיציה פתוחה ב-Binance Futures.
    משתמש ב־/fapi/v2/positionRisk כדי לזהות פוזיציות פתוחות,
    ואז שולח הוראת MARKET הפוכה כדי לסגור.
    """
    client = get_client()
    symbol = symbol.upper().strip()

    try:
        positions = client.futures_position_information(symbol=symbol)
        for pos in positions:
            amt = float(pos.get("positionAmt", 0))
            if amt != 0:
                side = "SELL" if amt > 0 else "BUY"
                order = client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    type="MARKET",
                    quantity=abs(amt)
                )
                logger.info(f"[Force Close] {symbol} amt={amt} closed with orderId={order.get('orderId')}")
                return {
                    "symbol": symbol,
                    "closedAmt": amt,
                    "side": side,
                    "orderId": order.get("orderId")
                }
        return {"symbol": symbol, "closedAmt": 0, "message": "no open position"}
    except BinanceAPIException as e:
        logger.error(f"[Binance] Force close failed: {e}")
        raise RuntimeError(f"Binance API error: {e}")
    except Exception as e:
        logger.error(f"[Binance] Unexpected force close error: {e}")
        raise RuntimeError(f"Unexpected error: {e}")

































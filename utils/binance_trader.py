# utils/binance_trader.py
import logging
from utils.binance_client import futures_mark_price, _signed_request

logger = logging.getLogger("algogpt.binance.trader")


async def binance_futures_trade(
    symbol: str,
    side: str,
    budget: float,
    leverage: int = 10,
    dry_run: bool = False,
) -> dict:
    """
    ביצוע טרייד ב-Binance Futures.
    אם dry_run=True → מחזיר סימולציה בלבד.
    """
    symbol = symbol.upper().strip()
    side = side.upper().strip()

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
            "leverage": leverage,
        }

    try:
        # שינוי מינוף
        _signed_request("POST", "fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})

        # יצירת פקודת MARKET
        order = _signed_request(
            "POST",
            "fapi/v1/order",
            {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty},
        )

        entry_price = float(order.get("avgPrice") or order.get("price") or price)

        return {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry": entry_price,
            "leverage": leverage,
        }
    except Exception as e:
        logger.error(f"[Binance] Trade failed: {e}")
        raise RuntimeError(f"Binance trade error: {e}")


def force_close_position(symbol: str) -> dict:
    """
    סוגר פוזיציה פתוחה ב-Binance Futures.
    שולף positionRisk ואז שולח הוראת MARKET הפוכה.
    """
    symbol = symbol.upper().strip()

    try:
        positions = _signed_request("GET", "fapi/v2/positionRisk", {"symbol": symbol})
        for pos in positions:
            amt = float(pos.get("positionAmt", 0))
            if amt != 0:
                side = "SELL" if amt > 0 else "BUY"
                order = _signed_request(
                    "POST",
                    "fapi/v1/order",
                    {"symbol": symbol, "side": side, "type": "MARKET", "quantity": abs(amt)},
                )
                logger.info(f"[Force Close] {symbol} amt={amt} closed with orderId={order.get('orderId')}")
                return {"symbol": symbol, "closedAmt": amt, "side": side, "orderId": order.get("orderId")}
        return {"symbol": symbol, "closedAmt": 0, "message": "no open position"}
    except Exception as e:
        logger.error(f"[Binance] Force close failed: {e}")
        raise RuntimeError(f"Force close error: {e}")


































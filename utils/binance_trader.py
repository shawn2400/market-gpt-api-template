# utils/binance_trader.py

import logging
from utils.binance_client import client
import asyncio

async def place_futures_order(symbol, side, quantity, entry_price, stop_loss, take_profit, leverage=10):
    """
    שולח פקודת פיוצ'רס עם SL ו־TP ל־Binance (MARKET).
    """
    try:
        loop = asyncio.get_running_loop()

        # שינוי מינוף
        await loop.run_in_executor(None, lambda: client.futures_change_leverage(symbol=symbol, leverage=leverage))

        # פקודת שוק ראשית
        order = await loop.run_in_executor(None, lambda: client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=quantity
        ))
        logging.info(f"[BINANCE] ✅ פקודת שוק: {symbol} {side} {quantity}")

        opposite_side = "SELL" if side.upper() == "BUY" else "BUY"

        # SL
        await loop.run_in_executor(None, lambda: client.futures_create_order(
            symbol=symbol,
            side=opposite_side,
            type="STOP_MARKET",
            stopPrice=round(float(stop_loss), 4),
            closePosition=True,
            timeInForce="GTC",
            workingType="MARK_PRICE"
        ))
        logging.info(f"[BINANCE] 📉 SL: {stop_loss}")

        # TP
        await loop.run_in_executor(None, lambda: client.futures_create_order(
            symbol=symbol,
            side=opposite_side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=round(float(take_profit), 4),
            closePosition=True,
            timeInForce="GTC",
            workingType="MARK_PRICE"
        ))
        logging.info(f"[BINANCE] 📈 TP: {take_profit}")

        return {
            "symbol": symbol,
            "quantity": quantity,
            "entry": entry_price,
            "pnl": 0.0,
            "timestamp": order.get("updateTime", 0)
        }

    except Exception as e:
        logging.error(f"[BINANCE] ❌ שגיאה בשליחת פקודה ל־{symbol}: {e}")
        return {
            "symbol": symbol,
            "quantity": 0,
            "entry": entry_price,
            "pnl": 0.0,
            "timestamp": 0,
            "error": str(e)
        }

async def binance_futures_trade(
    symbol, side, entry, sl, tp, leverage, budget, market_type="futures"
):
    """
    עטיפה נוחה – מחשבת כמות לפי תקציב, שולחת פקודה חיה. (ASYNC)
    """
    order_side = "BUY" if side.upper() == "LONG" else "SELL"
    entry_price = float(entry)
    quantity = float(budget) / entry_price
    quantity = round(quantity, 4)  # שיפור עתידי: dynamic לפי stepSize

    result = await place_futures_order(
        symbol=symbol,
        side=order_side,
        quantity=quantity,
        entry_price=entry_price,
        stop_loss=sl,
        take_profit=tp,
        leverage=leverage
    )
    return result















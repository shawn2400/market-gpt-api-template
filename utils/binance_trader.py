# utils/binance_trader.py

import logging
from utils.binance_client import client

async def place_futures_order(symbol, side, quantity, entry_price, stop_loss, take_profit, leverage=10):
    """
    שולח פקודת פיוצ'רס עם SL ו־TP מסוג MARKET ל־Binance.
    """
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=quantity
        )
        logging.info(f"[BINANCE] ✅ פקודת שוק נשלחה: {symbol} {side} {quantity}")

        opposite_side = "SELL" if side.upper() == "BUY" else "BUY"

        client.futures_create_order(
            symbol=symbol,
            side=opposite_side,
            type="STOP_MARKET",
            stopPrice=round(float(stop_loss), 4),
            closePosition=True,
            timeInForce="GTC",
            workingType="MARK_PRICE"
        )
        logging.info(f"[BINANCE] 📉 SL נשלח: {stop_loss}")

        client.futures_create_order(
            symbol=symbol,
            side=opposite_side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=round(float(take_profit), 4),
            closePosition=True,
            timeInForce="GTC",
            workingType="MARK_PRICE"
        )
        logging.info(f"[BINANCE] 📈 TP נשלח: {take_profit}")

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

def binance_futures_trade(
    symbol, side, entry, sl, tp, leverage, budget, market_type="futures"
):
    """
    עטיפה נוחה – מחשב כמות לפי תקציב, שולח פקודה חיה.
    side: "LONG"/"SHORT"
    """
    order_side = "BUY" if side.upper() == "LONG" else "SELL"
    entry_price = float(entry)
    quantity = float(budget) / entry_price
    quantity = round(quantity, 4)  # לשפר ל־stepSize בפועל אם תרצה

    import asyncio
    result = asyncio.run(
        place_futures_order(
            symbol=symbol,
            side=order_side,
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=sl,
            take_profit=tp,
            leverage=leverage
        )
    )
    return result













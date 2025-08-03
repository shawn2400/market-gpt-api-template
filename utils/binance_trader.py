# utils/binance_trader.py

import logging
from utils.binance_client import client

def calc_quantity(symbol, entry, budget, leverage):
    # כאן צריך פונקציה שמחשבת כמות נכונה (ביטול עיגול יתר, תמיכה בתקני Binance).
    qty = round(float(budget) * float(leverage) / float(entry), 3)
    return qty

def binance_futures_trade(symbol, side, entry, sl, tp, leverage=10, budget=100, market_type="futures"):
    """
    מבצע טרייד לייב בפיוצ'רס עם SL ו-TP דרך Binance API (Market).
    """
    try:
        # מחשב כמות נכונה
        qty = calc_quantity(symbol, entry, budget, leverage)

        # קביעת כיוון (Buy/Long, Sell/Short)
        if side.upper() == "LONG":
            order_side = "BUY"
        elif side.upper() == "SHORT":
            order_side = "SELL"
        else:
            raise ValueError("Side must be 'LONG' or 'SHORT'")

        # קריאה לפונקציה הא-סינכרונית (אפשר להריץ אותה כאן sync כי אין await)
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            place_futures_order(symbol, order_side, qty, entry, sl, tp, leverage)
        )
        return result

    except Exception as e:
        logging.error(f"[BINANCE] ❌ שגיאה כללית: {e}")
        return {
            "symbol": symbol,
            "quantity": 0,
            "entry": entry,
            "pnl": 0.0,
            "timestamp": 0,
            "error": str(e)
        }


async def place_futures_order(symbol, side, quantity, entry_price, stop_loss, take_profit, leverage=10):
    """
    שולח פקודת פיוצ'רס עם SL ו־TP מסוג MARKET ל־Binance.
    """
    try:
        # הגדרת מינוף
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        # פקודת שוק (כניסה)
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=quantity
        )
        logging.info(f"[BINANCE] ✅ פקודת שוק נשלחה: {symbol} {side} {quantity}")

        # חישוב צד הפוך
        opposite_side = "SELL" if side.upper() == "BUY" else "BUY"

        # שליחת SL
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

        # שליחת TP
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



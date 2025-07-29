# utils/binance_trader.py

import logging
from utils.binance_client import client

async def place_futures_order(symbol, side, quantity, entry_price, stop_loss, take_profit, leverage=10):
    """
    שולח פקודת פיוצ'רס עם SL ו־TP מסוג MARKET ל־Binance.
    """
    try:
        # הגדרת מינוף
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        # פקודת שוק
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=quantity
        )
        logging.info(f"[BINANCE] ✅ פקודת שוק נשלחה: {symbol} {side} {quantity}")

        # פקודת STOP
        client.futures_create_order(
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            type="STOP_MARKET",
            stopPrice=round(stop_loss, 4),
            closePosition=True,
            timeInForce="GTC"
        )
        logging.info(f"[BINANCE] 📉 SL נשלח: {stop_loss}")

        # פקודת TP
        client.futures_create_order(
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            type="TAKE_PROFIT_MARKET",
            stopPrice=round(take_profit, 4),
            closePosition=True,
            timeInForce="GTC"
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
        logging.error(f"[BINANCE] ❌ שגיאה בשליחת פקודה: {e}")
        return {
            "symbol": symbol,
            "quantity": 0,
            "entry": entry_price,
            "pnl": 0.0,
            "timestamp": 0
        }

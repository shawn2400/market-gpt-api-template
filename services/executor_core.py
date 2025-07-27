# services/executor_core.py

from binance.client import Client
from binance.enums import *
from dotenv import load_dotenv
import os
import time
import logging

load_dotenv()

api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
client = Client(api_key, api_secret)

def execute_trade_live(symbol, entry, stop, tp, direction, leverage, budget_usd=100, use_grid=False):
    try:
        logging.info(f"[LIVE TRADE] התחלת טרייד: {symbol} {direction} @ {entry} עם מינוף {leverage} ותקציב ${budget_usd}")

        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        qty = round((budget_usd * leverage) / entry, 3)

        side = SIDE_BUY if direction.upper() == "LONG" else SIDE_SELL

        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=qty
        )

        stop_side = SIDE_SELL if side == SIDE_BUY else SIDE_BUY

        client.futures_create_order(
            symbol=symbol,
            side=stop_side,
            type=ORDER_TYPE_STOP_MARKET,
            stopPrice=round(stop, 3),
            closePosition=True,
            timeInForce=TIME_IN_FORCE_GTC
        )

        client.futures_create_order(
            symbol=symbol,
            side=stop_side,
            type=ORDER_TYPE_LIMIT,
            price=round(tp, 3),
            closePosition=True,
            timeInForce=TIME_IN_FORCE_GTC
        )

        logging.info(f"[LIVE TRADE] ✅ טרייד נשלח לבינאנס: {symbol} {direction} | qty={qty}")
        return {"status": "success", "symbol": symbol, "entry": entry, "qty": qty, "tp": tp, "stop": stop}
    except Exception as e:
        logging.error(f"[LIVE TRADE] ❌ שגיאה בביצוע טרייד: {e}")
        return {"status": "error", "message": str(e)}


# trade_executor.py

import os
import json
import time
from binance.client import Client
from binance.enums import *

from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

client = Client(API_KEY, API_SECRET)

# ✅ פונקציה לשליחת טרייד בפועל ל־Binance Futures
def execute_trade_live(symbol, side, quantity, entry_price, stop_price, tp_price, leverage=20):
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        side_binance = SIDE_BUY if side.upper() == 'LONG' else SIDE_SELL

        order = client.futures_create_order(
            symbol=symbol,
            side=side_binance,
            type=ORDER_TYPE_MARKET,
            quantity=quantity
        )

        # 🛡️ הצבת TP ו־SL דרך OCO (או פקודות נפרדות)
        time.sleep(1)
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side.upper() == 'LONG' else SIDE_BUY,
            type=ORDER_TYPE_STOP_MARKET,
            stopPrice=round(stop_price, 2),
            closePosition=True
        )
        time.sleep(1)
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side.upper() == 'LONG' else SIDE_BUY,
            type=ORDER_TYPE_LIMIT,
            price=round(tp_price, 2),
            timeInForce=TIME_IN_FORCE_GTC,
            closePosition=True
        )

        return {"status": "ok", "order": order}
    except Exception as e:
        return {"status": "failed", "error": str(e)}







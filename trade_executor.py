import os
import json
import time
from binance.client import Client
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

client = Client(API_KEY, API_SECRET)

def execute_trade_live(symbol, entry_price, stop_price, tp_price, direction, leverage):
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        side = Client.SIDE_BUY if direction.upper() == "LONG" else Client.SIDE_SELL
        position_side = "LONG" if direction.upper() == "LONG" else "SHORT"

        # פתיחת פקודת מרקט
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=calculate_quantity(symbol, entry_price, leverage),
        )

        order_id = order["orderId"]

        # הגדרת TP
        client.futures_create_order(
            symbol=symbol,
            side=Client.SIDE_SELL if side == Client.SIDE_BUY else Client.SIDE_BUY,
            type="TAKE_PROFIT_MARKET",
            stopPrice=tp_price,
            closePosition=True,
            workingType="MARK_PRICE",
            timeInForce="GTC"
        )

        # הגדרת SL
        client.futures_create_order(
            symbol=symbol,
            side=Client.SIDE_SELL if side == Client.SIDE_BUY else Client.SIDE_BUY,
            type="STOP_MARKET",
            stopPrice=stop_price,
            closePosition=True,
            workingType="MARK_PRICE",
            timeInForce="GTC"
        )

        return {"status": "ok", "order_id": order_id}
    except Exception as e:
        return {"status": "failed", "error": str(e)}

def calculate_quantity(symbol, entry_price, leverage, usdt_amount=100):
    try:
        step_size = 0.01  # ברירת מחדל – ניתן לשפר בהמשך עם fetch exchange info
        qty = round((usdt_amount * leverage) / float(entry_price), 2)
        return max(step_size, qty)
    except:
        return 0.01






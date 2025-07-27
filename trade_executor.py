# trade_executor.py

from binance.client import Client
from binance.enums import *
import os
from dotenv import load_dotenv

# Load keys from .env file
load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_SECRET_KEY")
client = Client(API_KEY, API_SECRET)

def execute_trade(symbol, side, quantity, price=None, order_type="LIMIT", market_type="futures"):
    try:
        if market_type == "futures":
            if order_type == "LIMIT":
                order = client.futures_create_order(
                    symbol=symbol,
                    side=SIDE_BUY if side == "LONG" else SIDE_SELL,
                    type=ORDER_TYPE_LIMIT,
                    quantity=quantity,
                    price=str(price),
                    timeInForce=TIME_IN_FORCE_GTC
                )
            elif order_type == "MARKET":
                order = client.futures_create_order(
                    symbol=symbol,
                    side=SIDE_BUY if side == "LONG" else SIDE_SELL,
                    type=ORDER_TYPE_MARKET,
                    quantity=quantity
                )
        else:
            if order_type == "LIMIT":
                order = client.create_order(
                    symbol=symbol,
                    side=SIDE_BUY if side == "LONG" else SIDE_SELL,
                    type=ORDER_TYPE_LIMIT,
                    timeInForce=TIME_IN_FORCE_GTC,
                    quantity=quantity,
                    price=str(price)
                )
            elif order_type == "MARKET":
                order = client.create_order(
                    symbol=symbol,
                    side=SIDE_BUY if side == "LONG" else SIDE_SELL,
                    type=ORDER_TYPE_MARKET,
                    quantity=quantity
                )
        return {"status": "success", "order_id": order["orderId"]}
    except Exception as e:
        return {"status": "error", "message": str(e)}



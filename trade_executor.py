# trade_executor.py

from binance.client import Client
from binance.enums import *
import os

# שליפת מפתחות מהסביבה
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)

def execute_trade(symbol, side, quantity, order_type="MARKET", price=None, market_type="futures"):
    try:
        if market_type == "futures":
            client.futures_change_leverage(symbol=symbol, leverage=20)
            if order_type == "LIMIT" and price:
                order = client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    type=ORDER_TYPE_LIMIT,
                    quantity=quantity,
                    price=price,
                    timeInForce=TIME_IN_FORCE_GTC
                )
            else:
                order = client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    type=ORDER_TYPE_MARKET,
                    quantity=quantity
                )
        elif market_type == "spot":
            if order_type == "LIMIT" and price:
                order = client.order_limit(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=price
                )
            else:
                order = client.order_market(
                    symbol=symbol,
                    side=side,
                    quantity=quantity
                )
        else:
            return {"error": "Invalid market_type"}
        
        return order

    except Exception as e:
        return {"error": str(e)}


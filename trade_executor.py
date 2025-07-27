from binance.client import Client
from binance.enums import *
import os

api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
client = Client(api_key, api_secret)

def execute_trade(symbol, side, quantity, price=None, order_type="LIMIT", market_type="futures", trailing_percent=None):
    try:
        if market_type == "futures":
            params = {
                "symbol": symbol,
                "side": side.upper(),
                "quantity": quantity,
                "type": order_type
            }

            if order_type == "LIMIT":
                params["price"] = str(price)
                params["timeInForce"] = TIME_IN_FORCE_GTC

            elif order_type == "TRAILING_STOP_MARKET":
                params["callbackRate"] = float(trailing_percent or 1.0)

            order = client.futures_create_order(**params)
            return {"status": "success", "order": order}
        else:
            return {"error": "Only futures market supported at this time."}

    except Exception as e:
        return {"error": str(e)}




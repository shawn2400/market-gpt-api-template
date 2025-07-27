from binance.client import Client
from binance.enums import *
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
client = Client(api_key, api_secret)

def execute_trade(symbol, side, quantity, price=None, order_type="LIMIT", market_type="futures", trailing_percent=None):
    try:
        side = side.upper()

        if market_type == "futures":
            try:
                client.futures_change_leverage(symbol=symbol, leverage=20)
            except Exception:
                pass

            params = {
                "symbol": symbol,
                "side": side,
                "quantity": float(quantity),
                "type": order_type
            }

            if order_type == "LIMIT":
                if not price:
                    return {"error": "Missing price for LIMIT order"}
                params["price"] = str(price)
                params["timeInForce"] = TIME_IN_FORCE_GTC

            elif order_type == "TRAILING_STOP_MARKET":
                params["callbackRate"] = float(trailing_percent or 1.0)
                if price:
                    params["activationPrice"] = str(price)

            elif order_type == "MARKET":
                pass

            else:
                return {"error": f"Unsupported order_type: {order_type}"}

            print("\U0001F680 Executing order:", params)
            order = client.futures_create_order(**params)
            return {"status": "success", "order": order}

        else:
            return {"error": "Only futures market supported at this time."}

    except Exception as e:
        return {"error": f"Exception occurred: {str(e)}"}






import os
from dotenv import load_dotenv
from binance.client import Client
from binance.enums import *

# טען משתני סביבה
load_dotenv()

# קח את המפתחות
api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")

# אתחול הלקוח
client = Client(api_key, api_secret)

# 🧪 פרטי טרייד לבדיקה
symbol = "BTCUSDT"
side = SIDE_BUY
quantity = 0.001
order_type = "LIMIT"  # אפשר גם "TRAILING_STOP_MARKET"
price = "30000"
trailing_percent = 1.0

try:
    if order_type == "LIMIT":
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_LIMIT,
            timeInForce=TIME_IN_FORCE_GTC,
            quantity=quantity,
            price=price
        )
    elif order_type == "TRAILING_STOP_MARKET":
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_TRAILING_STOP_MARKET,
            quantity=quantity,
            callbackRate=trailing_percent,
            activationPrice="30500"  # אופציונלי אך מומלץ
        )
    else:
        raise Exception("Unsupported order type")

    print("✅ Order sent successfully:")
    print(order)

except Exception as e:
    print("❌ Error sending order:")
    print(str(e))

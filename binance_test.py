import os
from dotenv import load_dotenv
from binance.client import Client
from binance.enums import *

# טען משתני סביבה
load_dotenv()

# אתחול הלקוח
api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
client = Client(api_key, api_secret)

# בדיקת חיבור
print("🔐 Binance API Key Loaded:", bool(api_key))
print("🔌 Checking connection...")

try:
    account_info = client.futures_account()
    print("✅ Connected to Binance Futures!")
except Exception as e:
    print("❌ Failed to connect:", str(e))
    exit()

# 🧪 פרטי טרייד לבדיקה
symbol = "BTCUSDT"
side = SIDE_BUY
quantity = 0.001
order_type = "LIMIT"  # או "TRAILING_STOP_MARKET"
price = "30000"
trailing_percent = 1.0

print(f"\n🚀 Sending test order: {order_type} {symbol} {side}")

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
            activationPrice="30500"
        )
    else:
        raise Exception("Unsupported order type")

    print("✅ Order sent successfully:")
    print(order)

except Exception as e:
    print("❌ Error sending order:")
    print(str(e))

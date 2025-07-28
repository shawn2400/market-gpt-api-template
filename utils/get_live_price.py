import os
from binance.client import Client
from dotenv import load_dotenv

load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    raise EnvironmentError("❌ מפתחות Binance חסרים בקובץ .env")

try:
    client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    # בדיקת תקינות – פינג פשוט ל־Futures API
    client.futures_ping()
    print("✅ Binance Futures API connected successfully.")

except Exception as e:
    print(f"❌ שגיאה בהתחברות ל־Binance: {e}")
    client = None  # fallback – יש לבדוק client לפני כל שימוש



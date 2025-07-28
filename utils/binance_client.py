# utils/binance_client.py

import os
import logging
from binance.client import Client
from dotenv import load_dotenv

load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    raise ValueError("❌ BINANCE_API_KEY or BINANCE_API_SECRET missing in .env")

try:
    client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)
    status = client.futures_ping()
    logging.info("✅ Binance Futures API connected successfully.")
except Exception as e:
    logging.error(f"❌ שגיאה בחיבור ל־Binance API: {e}")
    client = None  # למניעת קריסה, אפשר לבדוק client לפני שימוש




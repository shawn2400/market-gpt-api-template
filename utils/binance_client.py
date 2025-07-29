# utils/binance_client.py

import os
import logging
from binance.client import Client
from dotenv import load_dotenv

# טעינת משתנים מהסביבה
load_dotenv()

# הגדרת לוגינג
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# מפתחות API
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

# אובייקט הלקוח
client = None

try:
    if not API_KEY or not API_SECRET:
        raise EnvironmentError("❌ מפתחות Binance API לא הוגדרו בקובץ .env")

    client = Client(API_KEY, API_SECRET)
    logging.info("✅ Binance client initialized (Spot & Futures)")

except Exception as e:
    logging.error(f"[!] שגיאה אתחול Binance client: {e}")











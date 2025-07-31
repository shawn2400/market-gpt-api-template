# utils/binance_client.py

import os
import logging
from dotenv import load_dotenv
from binance.client import Client

# טעינת משתני סביבה
load_dotenv()

# הגדרת לוגינג
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# קריאת מפתחות API
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

client = None

try:
    if not API_KEY or not API_SECRET:
        raise EnvironmentError("❌ מפתחות Binance API לא נמצאו בקובץ .env")

    # יצירת לקוח Binance
    client = Client(API_KEY, API_SECRET)

    # בדיקת תקשורת
    if client.ping() != {}:
        raise ConnectionError("❌ חיבור ל־Binance נכשל (ping שגוי)")

    logging.info("✅ Binance client מחובר (Spot + Futures)")

except Exception as e:
    logging.error(f"[Binance Client Error] {type(e).__name__}: {e}")
    client = None  # ביטול גישה במקרה שגיאה













# utils/binance_client.py

import os
import logging
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# טעינת משתני סביבה מקובץ .env
load_dotenv()

# הגדרת לוגינג
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')

# שליפת מפתחות Binance מהסביבה
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

client = None

def init_binance_client():
    global client
    try:
        if not API_KEY or not API_SECRET:
            raise EnvironmentError("❌ מפתחות Binance API לא מוגדרים בקובץ .env")

        # יצירת לקוח
        client = Client(API_KEY, API_SECRET)

        # בדיקת ping
        ping = client.ping()
        if ping != {}:
            raise ConnectionError(f"❌ שגיאה ב־ping ל־Binance: {ping}")

        # בדיקת גישה לחשבון
        account_info = client.futures_account()
        if "assets" not in account_info:
            raise ConnectionError("❌ לא ניתן לגשת לחשבון Futures")

        logging.info("✅ Binance client מחובר בהצלחה (Spot + Futures)")

    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"[Binance API Error] {type(e).__name__}: {e}")
        client = None
    except Exception as e:
        logging.error(f"[Binance Client Init Error] {type(e).__name__}: {e}")
        client = None

# אתחול אוטומטי ברגע טעינת המודול
init_binance_client()














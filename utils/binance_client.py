# utils/binance_client.py

import os
import logging
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# טען משתנים מהסביבה (רק אם קיים קובץ – ברנדר לא חובה)
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    force=True
)

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

client = None

def init_binance_client():
    global client
    try:
        if not API_KEY or not API_SECRET:
            raise EnvironmentError("❌ BINANCE_API_KEY or BINANCE_API_SECRET not set")
        client = Client(API_KEY, API_SECRET)
        # client.API_URL = "https://api1.binance.com/api"  # אופציונלי בלבד
        # בדיקת חיבור
        client.ping()
        client.futures_account()
        logging.info("✅ Binance client connected (Spot + Futures)")
    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"[Binance API Error] {e}")
        client = None
    except Exception as e:
        logging.error(f"[Binance Init Error] {e}")
        client = None

# הפעל אוטומטית בייבוא (גם אם מריצים ב־gunicorn)
init_binance_client()

# בדיקת client בייבוא (תשתמש בפונקציית health_check ליתר ביטחון)
if not client:
    logging.warning("[Binance] Client לא מאותחל – בדוק API KEY/SECRET בסביבה!")



























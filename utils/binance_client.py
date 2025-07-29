import os
import logging
from binance.client import Client
from binance.enums import *

# הגדרת לוגינג
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# טעינת מפתחות מהסביבה
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

client = None
futures_client = None

try:
    if API_KEY and API_SECRET:
        client = Client(API_KEY, API_SECRET)
        futures_client = client  # באותה ספריה - Futures ו-Spot באותו אובייקט
        client.FUTURES_URL = 'https://fapi.binance.com/fapi'
        logging.info("✅ Binance client initialized (Spot & Futures)")
    else:
        raise EnvironmentError("מפתחות BINANCE_API_KEY ו־BINANCE_API_SECRET לא הוגדרו")
except Exception as e:
    logging.error(f"[!] שגיאה בחיבור ל-Binance: {e}")










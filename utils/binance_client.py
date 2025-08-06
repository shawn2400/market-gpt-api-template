# utils/binance_client.py

import os
import logging
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# === טעינת משתני סביבה ===
load_dotenv()

# === קונפיג לוגים ===
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    force=True
)

# === קבלת מפתחות מהסביבה ===
API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

client = None

def init_binance_client():
    """
    מאתחל את הלקוח של Binance (Spot + Futures) אם קיימים מפתחות תקינים.
    """
    global client
    try:
        if not API_KEY or not API_SECRET:
            raise EnvironmentError("❌ BINANCE_API_KEY או BINANCE_API_SECRET לא הוגדרו")

        logging.info("[Binance] 🔑 מפתחות נמצאו – מנסה להתחבר...")
        temp_client = Client(API_KEY, API_SECRET)
        temp_client.API_URL = "https://api1.binance.com/api"

        # בדיקות תקשורת בסיסיות
        temp_client.ping()
        temp_client.futures_account()

        client = temp_client
        logging.info("✅ חיבור ל־Binance הצליח (Spot + Futures)")

    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"[Binance API Error] {e}")
        client = None
    except Exception as e:
        logging.error(f"[Binance Init Error] {e}")
        client = None

# אתחול ברגע ייבוא
init_binance_client()

if not client:
    logging.warning("⚠️ Binance client לא מאותחל – בדוק מפתחות או חיבור")

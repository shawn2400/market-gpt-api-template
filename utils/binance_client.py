# utils/binance_client.py

import os
import logging
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# === טעינת משתני סביבה ===
load_dotenv()

# === קונפיגורציית לוגים ===
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    force=True
)

# === טעינת מפתחות עם ניקוי רווחים מיותרים ===
API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

# --- לוג טעינת מפתחות חלקי (לשמירת פרטיות) ---
logging.info(f"[Env Check] BINANCE_API_KEY Loaded: {'Yes' if API_KEY else 'No'} (starts with: {API_KEY[:4] + '...' if API_KEY else 'None'})")
logging.info(f"[Env Check] BINANCE_API_SECRET Loaded: {'Yes' if API_SECRET else 'No'} (starts with: {API_SECRET[:4] + '...' if API_SECRET else 'None'})")

client = None

def init_binance_client():
    """
    מאתחל את הלקוח של Binance (Spot + Futures) אם קיימים מפתחות תקינים.
    """
    global client
    try:
        if not API_KEY or not API_SECRET:
            raise EnvironmentError("❌ BINANCE_API_KEY או BINANCE_API_SECRET לא הוגדרו או ריקים")

        logging.info("[Binance] 🔑 מפתחות נמצאו – מנסה להתחבר ל-Binance API...")
        temp_client = Client(API_KEY, API_SECRET)
        # ברירת מחדל, אפשר לשנות אם רוצים URL שונה
        temp_client.API_URL = "https://api1.binance.com/api"

        # בדיקות תקשורת בסיסיות
        temp_client.ping()
        # מוודא שיש גישה ל-Futures
        futures_acc_info = temp_client.futures_account()
        logging.info(f"[Binance] futures_account info sample: {str(futures_acc_info)[:200]}")

        client = temp_client
        logging.info("✅ חיבור ל־Binance הצליח (Spot + Futures)")

    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"[Binance API Error] {e}")
        client = None
    except EnvironmentError as ee:
        logging.error(f"[Binance Env Error] {ee}")
        client = None
    except Exception as e:
        logging.error(f"[Binance Init Error] {e}")
        client = None

# אתחול מידי טעינת הקובץ
init_binance_client()

def check_binance_client():
    """
    פונקציה לבדיקה ידנית שה-client מאותחל ותקין.
    """
    if client is None:
        logging.error("[Binance Client] Client is None - API keys probably invalid or not loaded.")
        return False
    try:
        res = client.ping()
        logging.info(f"[Binance Client] Ping successful: {res}")
        return True
    except Exception as e:
        logging.error(f"[Binance Client] Ping failed: {e}")
        return False

# לאפשר בדיקה ישירה בעת הרצה ישירה של הקובץ
if __name__ == "__main__":
    if check_binance_client():
        logging.info("Binance Client ready to use.")
    else:
        logging.error("Binance Client not ready. Check your API keys and environment variables.")



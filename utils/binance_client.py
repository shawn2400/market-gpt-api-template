import os
import logging
from dotenv import load_dotenv
from binance.client import Client

# טעינת משתני סביבה
load_dotenv()

# הגדרת לוגינג
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# מפתחות
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

client = None

try:
    if not API_KEY or not API_SECRET:
        raise EnvironmentError("❌ מפתחות Binance API לא הוגדרו בקובץ .env")

    client = Client(API_KEY, API_SECRET)

    # בדיקת התחברות בפועל
    ping = client.ping()
    if ping != {}:
        raise ConnectionError("❌ לא הצלחנו להתחבר ל־Binance API (ping נכשל)")

    logging.info("✅ Binance client initialized (Spot & Futures)")

except Exception as e:
    logging.error(f"[!] שגיאה אתחול Binance client: {type(e).__name__} – {e}")
    client = None  # ביטול גישה כדי לא לקרוס בקוד אחר












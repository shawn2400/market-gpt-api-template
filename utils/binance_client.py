import os
import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# לוגים פשוטים
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s', force=True)

client = None

def init_binance_client():
    global client
    try:
        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_API_SECRET")

        if not api_key or not api_secret:
            raise EnvironmentError("❌ BINANCE_API_KEY and BINANCE_API_SECRET must be set in environment.")

        client = Client(api_key, api_secret)

        # בדיקת תקשורת בסיסית
        client.ping()
        client.futures_account()  # ודא שיש הרשאות ל־Futures

        logging.info("✅ Binance client connected (Spot + Futures)")

    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"[Binance API Error] {e}")
        client = None
    except Exception as e:
        logging.error(f"[Binance Init Error] {e}")
        client = None

# הפעלה מיידית
init_binance_client()
























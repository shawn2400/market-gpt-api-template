# utils/binance_client.py

import os
import logging
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

 HEAD
# Load .env variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s', force=True)

# Get API keys from environment
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
=======
# טען את קובץ .env רק אם קיים (מיותר ב-Render)
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    force=True
)
 482a0dc2c1505e9f0ec5c361f3d8b43672d6fb04

client = None

def init_binance_client():
    global client
    try:
<<<<<<< HEAD
        if not API_KEY or not API_SECRET:
            raise EnvironmentError("❌ BINANCE_API_KEY or BINANCE_API_SECRET not set")

        client = Client(API_KEY, API_SECRET)

        # Optional: alternate API endpoint
        client.API_URL = "https://api1.binance.com/api"

        # Ping test
        client.ping()
        client.futures_account()

        logging.info("✅ Binance client connected (Spot + Futures)")
=======
        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_API_SECRET")

        if not api_key or not api_secret:
            raise EnvironmentError("❌ BINANCE_API_KEY or BINANCE_API_SECRET missing")

        client = Client(api_key, api_secret)

        # בדיקת חיבור Spot
        client.ping()

        # בדיקת חיבור Futures
        _ = client.futures_account()

        logging.info("✅ Connected to Binance Spot + Futures API")
 482a0dc2c1505e9f0ec5c361f3d8b43672d6fb04

    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"[Binance API Error] {e}")
        client = None
    except Exception as e:
        logging.error(f"[Binance Init Error] {e}")
        client = None

# אוטומטית בעת import
init_binance_client()

# בדיקה
if not client:
    logging.warning("⚠️ Binance client לא מאותחל – בדוק מפתחות או חיבור")
































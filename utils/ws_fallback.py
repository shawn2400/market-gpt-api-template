# utils/binance_client.py

import os
import logging
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# Load .env variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    force=True
)

# Get API keys from environment
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

client = None

def init_binance_client():
    global client
    try:
        if not API_KEY or not API_SECRET:
            raise EnvironmentError("❌ BINANCE_API_KEY or BINANCE_API_SECRET not set")

        client = Client(API_KEY, API_SECRET)
        client.API_URL = "https://api1.binance.com/api"

        # Basic connectivity tests
        client.ping()
        client.futures_account()
        logging.info("✅ Connected to Binance Spot + Futures API")
    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"[Binance API Error] {e}")
        client = None
    except Exception as e:
        logging.error(f"[Binance Init Error] {e}")
        client = None

# Auto-init at import
init_binance_client()

# Warn if not initialized
if not client:
    logging.warning("⚠️ Binance client לא מאותחל – בדוק מפתחות או חיבור")


















>>>>>>> 482a0dc2c1505e9f0ec5c361f3d8b43672d6fb04

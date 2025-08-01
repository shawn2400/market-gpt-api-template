# utils/binance_client.py

import os
import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# הגדרת לוגינג לקונסול
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')

API_KEY    = os.environ.get("BINANCE_API_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET")

client = None

def init_binance_client():
    global client
    if not API_KEY or not API_SECRET:
        logging.error("✖️ חסר ENV VAR: BINANCE_API_KEY או BINANCE_API_SECRET")
        return

    try:
        client = Client(API_KEY, API_SECRET)
        client.ping()
        client.futures_account()
        logging.info("✔️ התחבר לבייננס (Spot & Futures)")
    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"[Binance API Error] {e}")
        client = None
    except Exception as e:
        logging.error(f"[Binance Init Error] {e}")
        client = None

# קריאה באימפורט
init_binance_client()






















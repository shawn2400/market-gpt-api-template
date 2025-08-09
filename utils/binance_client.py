# utils/binance_client.py
import os, logging
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

load_dotenv()

API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()

if any(c in API_KEY+API_SECRET for c in ["\n", "\r", "\t", " "]):
    logging.error("[Env] BINANCE keys contain whitespace/newlines -> fix Railway variables.")
    
# הערה: Public (לסריקות/klines) לא דורש מפתח. הפקודות (Orders) כן.
if API_KEY and API_SECRET:
    client = Client(API_KEY, API_SECRET, tld="com")
else:
    logging.warning("[Binance] No API keys loaded -> public-only mode enabled.")
    client = Client(None, None, tld="com")

# Futures base (ליתר בטחון)
client.FUTURES_URL = "https://fapi.binance.com"

def ping_and_info():
    try:
        client.ping()                # Public
        ei = client.futures_exchange_info()
        logging.info(f"[Binance] futures tz={ei.get('timezone')}, symbols={len(ei.get('symbols', []))}")
        return True
    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"[Binance] API error: {e}")
        return False

BINANCE_READY = ping_and_info()





# utils/binance_client.py

import os
import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv

# טען משתנים מהסביבה
load_dotenv()

api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")

client = None

try:
    if not api_key or not api_secret:
        raise ValueError("❌ Binance API key or secret missing")

    # ⚠️ התחברות ל־Mainnet בלבד
    client = Client(api_key, api_secret)
    
    # נסה קריאה פשוטה לבדיקה
    account = client.get_account()
    logging.info("🔐 Connected to Binance ✅")
    logging.info(f"Account canTrade: {account.get('canTrade', 'N/A')}")

except BinanceAPIException as e:
    logging.error(f"[Binance API Error] {e}")
    client = None
except Exception as e:
    logging.error(f"[Binance Init Error] {e}")
    client = None




























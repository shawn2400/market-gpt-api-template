# utils/binance_client.py
from __future__ import annotations
import os
import logging
from binance.client import Client

# --- קונפיגורציה מתוך ENV ---
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
USE_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes")

logger = logging.getLogger("algogpt.binance")

if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    raise RuntimeError("Missing BINANCE_API_KEY or BINANCE_API_SECRET in environment")

# --- יצירת Binance Client ---
binance_client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

# מעבר ל־Testnet אם צריך
if USE_TESTNET:
    logger.warning("⚠️ Using Binance TESTNET endpoints")
    binance_client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
else:
    binance_client.FUTURES_URL = "https://fapi.binance.com/fapi"

# --- עטיפות עזר ---
def new_order(symbol: str, side: str, type: str, quantity: float, price: float = None, timeInForce: str = "GTC"):
    """
    שולח פקודת FUTURES ל־Binance.
    side: BUY / SELL
    type: LIMIT / MARKET / STOP
    """
    try:
        params = {
            "symbol": symbol,
            "side": side,
            "type": type,
            "quantity": quantity,
        }
        if type == "LIMIT" and price:
            params["price"] = price
            params["timeInForce"] = timeInForce

        order = binance_client.futures_create_order(**params)
        return order
    except Exception as e:
        logger.exception(f"Binance new_order failed: {e}")
        raise

def get_balance(asset: str = "USDT"):
    """ מחזיר יתרה בחשבון FUTURES """
    try:
        balances = binance_client.futures_account_balance()
        for b in balances:
            if b["asset"] == asset:
                return float(b["balance"])
        return 0.0
    except Exception as e:
        logger.exception(f"Binance get_balance failed: {e}")
        return 0.0

def get_position(symbol: str):
    """ מחזיר מצב פוזיציה ל־symbol ספציפי """
    try:
        positions = binance_client.futures_position_information(symbol=symbol)
        if positions:
            return positions[0]
        return None
    except Exception as e:
        logger.exception(f"Binance get_position failed: {e}")
        return None






































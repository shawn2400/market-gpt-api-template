import os
import time
import logging
from dotenv import load_dotenv
from binance.client import Client
from binance.enums import *

load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    raise ValueError("❌ BINANCE_API_KEY or BINANCE_API_SECRET missing in .env")

try:
    client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)
    client.futures_ping()
    logging.info("✅ Binance Futures API connected successfully.")
except Exception as e:
    logging.error(f"❌ שגיאה בחיבור ל־Binance API: {e}")
    client = None  # למניעת קריסה

async def place_futures_order(symbol, side, quantity, entry_price, stop_loss, take_profit, leverage=10):
    """
    מבצע הוראת FUTURES מסוג MARKET עם SL ו-TP
    """
    try:
        # שינוי מינוף
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        # הוראת שוק
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type=FUTURE_ORDER_TYPE_MARKET,
            quantity=quantity
        )

        # שליחת SL ו־TP בנפרד
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side == SIDE_BUY else SIDE_BUY,
            type=FUTURE_ORDER_TYPE_STOP_MARKET,
            stopPrice=round(stop_loss, 3),
            closePosition=True,
            timeInForce=TIME_IN_FORCE_GTC
        )

        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side == SIDE_BUY else SIDE_BUY,
            type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
            stopPrice=round(take_profit, 3),
            closePosition=True,
            timeInForce=TIME_IN_FORCE_GTC
        )

        return {
            "status": "success",
            "symbol": symbol,
            "entry_price": entry_price,
            "pnl": 0,
            "timestamp": int(time.time() * 1000)
        }

    except Exception as e:
        raise RuntimeError(f"❌ Binance order failed: {e}")





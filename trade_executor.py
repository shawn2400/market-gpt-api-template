from binance.client import Client
from binance.enums import *
from dotenv import load_dotenv
import os
import time
import math
import logging

load_dotenv()

# התחברות ל-Binance
api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
client = Client(api_key, api_secret)

# 🟢 ביצוע טרייד בפועל
def execute_trade_live(symbol, entry, stop, tp, direction, leverage, budget_usd=100, use_grid=False):
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        price = float(client.futures_symbol_ticker(symbol=symbol)["price"])
        quantity = round((budget_usd * leverage) / price, 3)

        side = SIDE_BUY if direction.upper() == "LONG" else SIDE_SELL
        opposite_side = SIDE_SELL if side == SIDE_BUY else SIDE_BUY

        # פתיחת פוזיציה
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=quantity
        )

        time.sleep(1)

        # הגדרת סטופ
        client.futures_create_order(
            symbol=symbol,
            side=opposite_side,
            type=ORDER_TYPE_STOP_MARKET,
            stopPrice=round(stop, 4),
            closePosition=True,
            timeInForce=TIME_IN_FORCE_GTC
        )

        # הגדרת טייק פרופיט
        client.futures_create_order(
            symbol=symbol,
            side=opposite_side,
            type=ORDER_TYPE_LIMIT,
            price=round(tp, 4),
            quantity=quantity,
            timeInForce=TIME_IN_FORCE_GTC
        )

        return {
            "status": "success",
            "symbol": symbol,
            "entry_price": price,
            "quantity": quantity,
            "stop": stop,
            "tp": tp,
            "leverage": leverage,
            "side": side
        }

    except Exception as e:
        logging.error(f"❌ שגיאה בביצוע טרייד: {e}")
        return {"status": "error", "message": str(e)}














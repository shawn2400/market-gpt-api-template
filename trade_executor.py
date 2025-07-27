# trade_executor.py

from binance.client import Client
from binance.enums import *
from dotenv import load_dotenv
import os
import logging
from utils.quantity_utils import calculate_quantity, generate_grid_levels
import time

load_dotenv()

api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
client = Client(api_key, api_secret)

def execute_trade_live(symbol, entry, stop, tp, direction, leverage, budget_usd=100, use_grid=False):
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        side = SIDE_BUY if direction == "LONG" else SIDE_SELL
        position_side = "LONG" if direction == "LONG" else "SHORT"

        quantity = calculate_quantity(budget_usd, entry, leverage)

        # פקודות רגילות או גריד
        if use_grid:
            grid_levels = generate_grid_levels(entry, tp, levels=3)
            for level in grid_levels:
                price = round(level, 4)
                client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    type=ORDER_TYPE_LIMIT,
                    quantity=quantity,
                    price=str(price),
                    timeInForce=TIME_IN_FORCE_GTC
                )
                time.sleep(0.3)
        else:
            client.futures_create_order(
                symbol=symbol,
                side=side,
                type=ORDER_TYPE_LIMIT,
                quantity=quantity,
                price=str(entry),
                timeInForce=TIME_IN_FORCE_GTC
            )

        # טריילינג SL
        sl_price = round(stop, 4)
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if direction == "LONG" else SIDE_BUY,
            type=ORDER_TYPE_STOP_MARKET,
            stopPrice=str(sl_price),
            closePosition=True,
            timeInForce=TIME_IN_FORCE_GTC
        )

        # TP רגיל
        tp_price = round(tp, 4)
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if direction == "LONG" else SIDE_BUY,
            type=ORDER_TYPE_LIMIT,
            quantity=quantity,
            price=str(tp_price),
            timeInForce=TIME_IN_FORCE_GTC
        )

        return {
            "status": "success",
            "symbol": symbol,
            "entry": entry,
            "stop": stop,
            "tp": tp,
            "leverage": leverage,
            "quantity": quantity,
            "budget": budget_usd,
            "grid_used": use_grid
        }

    except Exception as e:
        logging.error(f"[execute_trade_live] ❌ שגיאה בביצוע טרייד: {e}")
        return {"status": "error", "message": str(e)}













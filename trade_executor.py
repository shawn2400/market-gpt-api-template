# trade_executor.py

import time
import logging
from math import floor
from binance.enums import *
from utils.binance_client import client  # ודא שהקובץ הזה קיים

def round_quantity(symbol, quantity):
    try:
        info = client.futures_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                step_size = float([f for f in s["filters"] if f["filterType"] == "LOT_SIZE"][0]["stepSize"])
                return floor(quantity / step_size) * step_size
    except Exception as e:
        logging.error(f"[!] שגיאה בעיגול כמות: {e}")
    return round(quantity, 3)

def execute_trade_live(symbol, entry, stop, tp, direction, leverage, budget_usd=100, use_grid=False):
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        price = float(client.futures_symbol_ticker(symbol=symbol)["price"])

        quantity = (budget_usd * leverage) / price
        quantity = round_quantity(symbol, quantity)

        if quantity <= 0:
            raise ValueError("כמות לא חוקית (אולי תקציב נמוך מדי?)")

        side = SIDE_BUY if direction.upper() == "LONG" else SIDE_SELL
        opposite_side = SIDE_SELL if side == SIDE_BUY else SIDE_BUY

        client.futures_create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=quantity
        )

        time.sleep(0.5)

        client.futures_create_order(
            symbol=symbol,
            side=opposite_side,
            type=ORDER_TYPE_STOP_MARKET,
            stopPrice=round(stop, 4),
            closePosition=True,
            timeInForce=TIME_IN_FORCE_GTC
        )

        time.sleep(0.5)

        try:
            client.futures_create_order(
                symbol=symbol,
                side=opposite_side,
                type=ORDER_TYPE_LIMIT,
                price=round(tp, 4),
                quantity=quantity,
                timeInForce=TIME_IN_FORCE_GTC
            )
        except Exception as e:
            logging.warning(f"[!] טייק פרופיט נכשל: {e} — ממשיכים בלעדיו")

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
        logging.error(f"❌ שגיאה בביצוע טרייד ב־{symbol}: {e}")
        return {"status": "error", "message": str(e)}

















import os
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
    # חשוב: לא לקרוא כאן ל־client.futures_ping() – זה יקר ויכול להיכשל בהרצה!
    logging.info("✅ Binance Futures API client ready.")
except Exception as e:
    logging.error(f"❌ שגיאה בבניית Binance API client: {e}")
    client = None

def get_symbol_precision(symbol):
    try:
        info = client.futures_exchange_info()
        for s in info['symbols']:
            if s['symbol'] == symbol:
                step_size = None
                for f in s['filters']:
                    if f['filterType'] == 'LOT_SIZE':
                        step_size = float(f['stepSize'])
                        return step_size
    except Exception as e:
        logging.error(f"לא ניתן לקבל stepSize ל־{symbol}: {e}")
    return 0.01

def round_quantity(quantity, step_size):
    if step_size == 0:
        step_size = 0.01
    return round(round(quantity / step_size) * step_size, 8)

def place_futures_order(symbol, side, quantity, entry_price, stop_loss, take_profit, leverage=10):
    if client is None:
        raise RuntimeError("Binance client לא מחובר")

    try:
        step_size = get_symbol_precision(symbol)
        quantity = round_quantity(quantity, step_size)
        if quantity <= 0:
            raise ValueError("כמות לא חוקית אחרי עיגול stepSize")
        # מינוף
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        # פתיחת פקודה
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type=FUTURE_ORDER_TYPE_MARKET,
            quantity=quantity
        )
        # SL
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side == SIDE_BUY else SIDE_BUY,
            type=FUTURE_ORDER_TYPE_STOP_MARKET,
            stopPrice=round(stop_loss, 3),
            closePosition=True,
            timeInForce=TIME_IN_FORCE_GTC
        )
        # TP
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side == SIDE_BUY else SIDE_BUY,
            type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
            stopPrice=round(take_profit, 3),
            closePosition=True,
            timeInForce=TIME_IN_FORCE_GTC
        )
        logging.info(f"✅ טרייד FUTURES בוצע ({symbol}) כמות: {quantity} מחיר כניסה: {entry_price}")
        return {
            "status": "success",
            "symbol": symbol,
            "entry_price": entry_price,
            "pnl": 0,
            "timestamp": int(time.time() * 1000)
        }

    except Exception as e:
        logging.error(f"❌ Binance order failed: {e}")
        raise RuntimeError(f"❌ Binance order failed: {e}")






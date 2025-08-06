import asyncio
import websockets
import json
import logging
import time
import os
from binance.client import Client
from dotenv import load_dotenv

# --- טעינת ENV ---
load_dotenv()
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
MARKET_TYPE = os.getenv("MARKET_TYPE", "futures").lower()

# --- Binance REST Client ---
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

# --- מחירים חיים ---
_ws_prices = {}
live_timestamps = {}
_ws_task = None
_ws_symbols = set()
_WS_RUNNING = False

def _get_rest_price(symbol):
    try:
        if MARKET_TYPE == "spot":
            ticker = client.get_symbol_ticker(symbol=symbol)
            return float(ticker["price"])
        else:
            ticker = client.futures_symbol_ticker(symbol=symbol)
            return float(ticker["price"])
    except Exception as e:
        logging.warning(f"[ws_fallback] REST price error for {symbol}: {e}")
        return None

async def _multi_stream_ws(symbols):
    global _WS_RUNNING
    streams = "/".join([f"{s.lower()}@ticker" for s in symbols])
    url = f"wss://fstream.binance.com/stream?streams={streams}"
    logging.info(f"[ws_fallback] Connecting Multi-Stream WS: {url}")

    try:
        async with websockets.connect(url, ping_interval=None) as ws:
            _WS_RUNNING = True

            async def ping_forever():
                while _WS_RUNNING:
                    try:
                        await ws.ping()
                        await asyncio.sleep(25)
                    except Exception as e:
                        logging.warning(f"[ws_fallback] Ping error: {e}")
                        break

            ping_task = asyncio.create_task(ping_forever())

            async for msg in ws:
                try:
                    data = json.loads(msg)
                    payload = data.get("data", {})
                    symbol = payload.get("s")
                    price = payload.get("c")
                    if symbol and price:
                        _ws_prices[symbol] = float(price)
                        live_timestamps[symbol] = time.time()
                except Exception as e:
                    logging.warning(f"[ws_fallback] Message error: {e}")

    except Exception as e:
        logging.error(f"[ws_fallback] WS connection failed: {e}")
    finally:
        _WS_RUNNING = False
        logging.warning(f"[ws_fallback] WS closed. Will try to reconnect in 5s...")
        await asyncio.sleep(5)
        await launch_multi_websocket(list(_ws_symbols))

async def launch_multi_websocket(symbols):
    """
    מפעיל את חיבור ה־Multi-Stream ל־Binance עבור רשימת סימבולים (עד 100).
    """
    global _ws_task, _ws_symbols, _WS_RUNNING
    symbols = [s.upper() for s in symbols]
    # אם אין שינוי ברשימת הסימבולים, לא מפעיל מחדש
    if set(symbols) == _ws_symbols and _WS_RUNNING:
        logging.info("[ws_fallback] WS already running for same symbols, skipping relaunch.")
        return
    _ws_symbols = set(symbols)
    _WS_RUNNING = False
    await asyncio.sleep(0.2)  # זמן קצר לשחרור WS קודם

    # מפסיק חיבור קודם (אם היה)
    if _ws_task and not _ws_task.done():
        _ws_task.cancel()
        try:
            await _ws_task
        except Exception:
            pass

    # מפעיל WS חדש
    _ws_task = asyncio.create_task(_multi_stream_ws(symbols))
    logging.info(f"[ws_fallback] Multi-Stream WS launched for: {', '.join(symbols)}")

async def get_price(symbol):
    """
    מחזיר מחיר חי (מה־WS). אם אין — נופל ל־REST אוטומטי.
    """
    symbol = symbol.upper()
    price = _ws_prices.get(symbol)
    if price:
        return price
    # fallback ל־REST (לא חוסם event loop)
    return await asyncio.to_thread(_get_rest_price, symbol)

def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    """
    בדיקה אם המחיר האחרון של symbol נחשב עדכני (ב־max_age_sec האחרונות).
    """
    ts = live_timestamps.get(symbol)
    if not ts:
        return False
    return (time.time() - ts) <= max_age_sec

# דוגמה להפעלה (פשוט תייבא וקרא):
# await launch_multi_websocket(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
# price = await get_price("BTCUSDT")













 

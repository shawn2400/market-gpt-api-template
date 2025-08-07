import asyncio
import websockets
import json
import logging
import time
import random
import os
from binance.client import Client
from dotenv import load_dotenv

# --- טעינת ENV ---
load_dotenv()
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
MARKET_TYPE = os.getenv("MARKET_TYPE", "futures").lower()
PING_INTERVAL = float(os.getenv("WS_PING_INTERVAL", 25))
BACKOFF_BASE = float(os.getenv("WS_BACKOFF_BASE", 5))
BACKOFF_MAX = float(os.getenv("WS_BACKOFF_MAX", 60))

# --- Binance REST Client ---
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

# --- מחירים חיים ---
_ws_prices = {}
live_timestamps = {}
_ws_task = None
_ws_symbols = set()
_WS_RUNNING = False

async def _multi_stream_ws(symbols):
    global _WS_RUNNING
    backoff = BACKOFF_BASE

    symbols = [s.upper() for s in symbols]
    connect_attempt = 0
    try:
        while True:
            connect_attempt += 1
            streams = "/".join([f"{s.lower()}@ticker" for s in symbols])
            url = f"wss://fstream.binance.com/stream?streams={streams}"
            logging.info(f"[ws_fallback] Attempt #{connect_attempt}: Connecting Multi-Stream WS: {url}")

            try:
                async with websockets.connect(url, ping_interval=None) as ws:
                    _WS_RUNNING = True

                    async def ping_forever():
                        while _WS_RUNNING:
                            try:
                                await ws.ping()
                                await asyncio.sleep(PING_INTERVAL)
                            except asyncio.CancelledError:
                                logging.info("[ws_fallback] Ping task cancelled.")
                                break
                            except Exception as e:
                                logging.warning(f"[ws_fallback] Ping error: {e}")

                    ping_task = asyncio.create_task(ping_forever())

                    try:
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
                    except asyncio.CancelledError:
                        logging.info("[ws_fallback] WebSocket listener cancelled.")
                        await ws.close()
                        break
                    finally:
                        ping_task.cancel()
                        try:
                            await ping_task
                        except asyncio.CancelledError:
                            pass

            except (websockets.exceptions.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK) as e:
                logging.warning(f"[ws_fallback] WS connection closed: {e}")
            except Exception as e:
                logging.error(f"[ws_fallback] WS connection failed: {e}")

            _WS_RUNNING = False
            wait_time = backoff + random.uniform(0, 2)  # jitter
            logging.warning(f"[ws_fallback] WS closed. Will try to reconnect in {wait_time:.1f}s...")
            await asyncio.sleep(wait_time)
            backoff = min(backoff * 2, BACKOFF_MAX)

    except asyncio.CancelledError:
        logging.info("[ws_fallback] _multi_stream_ws cancelled, exiting cleanly.")
        _WS_RUNNING = False
        raise

async def launch_multi_websocket(symbols):
    global _ws_task, _ws_symbols, _WS_RUNNING
    symbols = [s.upper() for s in symbols]
    if set(symbols) == _ws_symbols and _WS_RUNNING:
        logging.info("[ws_fallback] WS already running for same symbols, skipping relaunch.")
        return
    _ws_symbols = set(symbols)
    _WS_RUNNING = False
    await asyncio.sleep(0.2)

    if _ws_task and not _ws_task.done():
        _ws_task.cancel()
        try:
            await _ws_task
        except Exception:
            pass

    _ws_task = asyncio.create_task(_multi_stream_ws(symbols))
    logging.info(f"[ws_fallback] Multi-Stream WS launched for: {', '.join(symbols)}")

async def get_price(symbol):
    symbol = symbol.upper()
    price = _ws_prices.get(symbol)
    if price:
        return price
    return await asyncio.to_thread(_get_rest_price, symbol)

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

def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    ts = live_timestamps.get(symbol)
    if not ts:
        return False
    return (time.time() - ts) <= max_age_sec

async def launch_filtered_websocket(trade_data: list, min_quality: float = 6.0, max_symbols: int = 15):
    """
    מפעיל WebSocket רק עבור סמלים עם ציון איכות מעל סף.
    trade_data: רשימת מילונים עם keys 'symbol' ו- 'quality_score'
    """
    try:
        filtered_symbols = [entry["symbol"].upper() for entry in trade_data if entry.get("quality_score", 0) >= min_quality]
        symbols_to_launch = filtered_symbols[:max_symbols]

        if not symbols_to_launch:
            logging.warning("[ws_fallback] ⚠️ לא נמצאו סמלים שעומדים בסף האיכות להפעלה")
            return

        logging.info(f"[ws_fallback] מפעיל WebSocket עבור סמלים (מסונן): {symbols_to_launch}")

        await launch_multi_websocket(symbols_to_launch)

    except Exception as e:
        logging.error(f"[ws_fallback] ❌ שגיאה ב-launch_filtered_websocket: {e}")






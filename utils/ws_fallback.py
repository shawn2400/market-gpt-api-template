import asyncio
import json
import logging
import aiohttp

BINANCE_WS_URL = "wss://fstream.binance.com/stream?streams="

class BinanceWSManager:
    def __init__(self, symbols):
        self.symbols = [s.lower() for s in symbols]
        self.ws = None
        self.prices = {}
        self.connected = False
        self._lock = asyncio.Lock()

    async def connect(self):
        streams = "/".join(f"{s}@bookTicker" for s in self.symbols)
        url = BINANCE_WS_URL + streams
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url) as ws:
                self.ws = ws
                self.connected = True
                logging.info(f"[ws_fallback] WS connected to Binance for {len(self.symbols)} symbols")
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        symbol = data["data"]["s"]
                        price = float(data["data"]["a"])  # ask price
                        async with self._lock:
                            self.prices[symbol] = price
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logging.error(f"[ws_fallback] WS error: {msg.data}")
                        break

    async def get_price(self, symbol: str):
        async with self._lock:
            return self.prices.get(symbol.upper())

binance_ws_manager = None

async def launch_multi_websocket(symbols):
    global binance_ws_manager
    if binance_ws_manager is not None:
        return  # Already running
    binance_ws_manager = BinanceWSManager(symbols)
    asyncio.create_task(binance_ws_manager.connect())

async def get_price(symbol: str):
    global binance_ws_manager
    if binance_ws_manager is None:
        raise Exception("WebSocket not started")
    price = await binance_ws_manager.get_price(symbol)
    if price is None:
        # fallback ל-REST כאן (למימוש נוסף)
        logging.warning(f"[ws_fallback] Price not found in WS cache for {symbol}")
        return None
    return price

def is_price_fresh(symbol: str, max_age_sec: int = 10):
    # אפשר להוסיף לוגיקה לניטור זמן עדכון מחיר
    return True










import asyncio
import websockets
import json
import logging
import requests
from typing import Dict, List

live_prices: Dict[str, float] = {}
WS_CLIENT_STARTED = False

def load_symbols_from_watchlist() -> List[str]:
    try:
        with open("watchlist.json", "r") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [entry["symbol"].lower() for entry in data if isinstance(entry, dict) and "symbol" in entry]
    except Exception as e:
        logging.warning(f"[ws_fallback] שגיאה בטעינת watchlist.json: {e}")
    return ["btcusdt"]

async def ws_multi_stream(symbols: List[str]):
    if not symbols:
        symbols = ["btcusdt"]
    # בניית ה-URL לכל הסימבולים
    streams = "/".join([f"{s}@ticker" for s in symbols])
    ws_url = f"wss://fstream.binance.com/stream?streams={streams}"
    logging.info(f"[ws_fallback] WebSocket URL: {ws_url}")
    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                logging.info("[ws_fallback] Multi-stream WebSocket מחובר.")
                async for msg in ws:
                    data = json.loads(msg)
                    symbol = data.get("data", {}).get("s")
                    price = data.get("data", {}).get("c")
                    if symbol and price:
                        live_prices[symbol.upper()] = float(price)
        except Exception as e:
            logging.warning(f"[ws_fallback] שגיאת חיבור WS: {e}")
        await asyncio.sleep(5)  # ניסיון להתחבר מחדש לאחר 5 שניות

def launch_websocket_multi():
    """
    הפעלת WebSocket Multi-stream לכל הסימבולים מה־watchlist.json.
    אין להפעיל חיבור WS בודד לכל מטבע!
    קריאה אחת בלבד בפרויקט (מה-main.py).
    """
    global WS_CLIENT_STARTED
    if WS_CLIENT_STARTED:
        return
    WS_CLIENT_STARTED = True
    symbols = load_symbols_from_watchlist()
    loop = asyncio.get_event_loop()
    loop.create_task(ws_multi_stream(symbols))
    logging.info(f"[ws_fallback] WebSocket Multi-Stream הופעל עבור {len(symbols)} סימבולים.")

def get_price(symbol: str) -> float:
    """
    מחזיר מחיר חי מסימבול. אם אין WS פעיל, מבצע fallback ל-REST API.
    """
    symbol = symbol.upper()
    price = live_prices.get(symbol)
    if price:
        return price
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        return float(resp.json()["price"])
    except Exception as e:
        logging.warning(f"[ws_fallback] Fallback REST price for {symbol}: {e}")
        return None









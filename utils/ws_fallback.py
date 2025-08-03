import threading
import json
import time
import requests
import logging
from websocket import WebSocketApp
from typing import Dict, List

live_prices: Dict[str, float] = {}
live_prices_time: Dict[str, float] = {}  # <--- טיימסטמפ עדכון אחרון
ws_status: Dict[str, bool] = {}
MAX_CONNECTIONS = 1      # Multi-stream = 1 בלבד

def _on_message_multi(ws, message):
    try:
        data = json.loads(message)
        # Multi-stream: {"stream": "btcusdt@trade", "data": {...}}
        if "data" in data and "s" in data["data"] and "p" in data["data"]:
            symbol = data["data"]["s"].upper()
            price = float(data["data"]["p"])
            live_prices[symbol] = price
            live_prices_time[symbol] = time.time()  # זמן עדכון
            logging.debug(f"[WS-MULTI] {symbol} price updated: {price}")
        else:
            logging.debug(f"[WS-MULTI] Received: {data}")
    except Exception as e:
        logging.warning(f"[WS-MULTI] Failed to parse message: {e}")

def _on_error(ws, error):
    logging.warning(f"[WS-MULTI] Error: {error}")

def _on_close(ws, code, reason):
    logging.warning(f"[WS-MULTI] Closed: {code} / {reason}")
    ws_status["multi"] = False

def _on_open(ws):
    logging.info("[WS-MULTI] Connection opened")
    ws_status["multi"] = True

def launch_multi_websocket(symbols: List[str]):
    """
    הפעל WS multi-stream למסחר Binance – סימבולים מה־watchlist.
    """
    if ws_status.get("multi", False):
        logging.info("[WS-MULTI] Multi-stream already active")
        return

    streams = "/".join(f"{s.lower()}@trade" for s in symbols)
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"

    def run_ws():
        ws = WebSocketApp(
            url,
            on_open=_on_open,
            on_message=_on_message_multi,
            on_error=_on_error,
            on_close=_on_close,
        )
        try:
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            logging.warning(f"[WS-MULTI] run_forever failed: {e}")
        finally:
            ws_status["multi"] = False
            time.sleep(5)
            logging.info("[WS-MULTI] Reconnecting multi-stream...")
            launch_multi_websocket(symbols)  # אוטומטי ריקונקט

    t = threading.Thread(target=run_ws, daemon=True)
    t.start()
    ws_status["multi"] = True

def is_price_fresh(symbol: str, max_age: int = 3) -> bool:
    """
    בדיקת עדכניות מחיר חי (max_age בשניות).
    מחזיר True אם המחיר עודכן ב־max_age האחרונות, אחרת False.
    """
    now = time.time()
    ts = live_prices_time.get(symbol.upper())
    if ts is None:
        return False
    return now - ts <= max_age

def get_price(symbol: str, max_age: int = 3) -> float:
    """
    מחזיר מחיר חי מסימבול רק אם הוא עדכני (max_age שניות), אחרת מנסה REST fallback.
    """
    symbol = symbol.upper()
    price = live_prices.get(symbol)
    if price is not None and is_price_fresh(symbol, max_age=max_age):
        return price
    # מחיר WS לא עדכני — ננסה REST
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        price = float(resp.json()["price"])
        # נעדכן גם את cache כדי שהWS לא ישבור לנו
        live_prices[symbol] = price
        live_prices_time[symbol] = time.time()
        return price
    except Exception as e:
        logging.warning(f"[Fallback] Failed to fetch REST price for {symbol}: {e}")
        return None

def get_active_ws_symbols():
    if ws_status.get("multi", False):
        return list(live_prices.keys())
    return []













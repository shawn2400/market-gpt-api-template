# utils/ws_fallback.py

import threading
import json
import time
import requests
import logging
from websocket import WebSocketApp

# קאש למחירים חיים
live_prices = {}
ws_connections = {}

# === WebSocket Listener עבור Binance ===
def _on_message(ws, message, symbol):
    try:
        data = json.loads(message)
        price = float(data["p"])
        live_prices[symbol] = price
        logging.debug(f"[WS] {symbol} price updated: {price}")
    except Exception as e:
        logging.warning(f"[WS] Error parsing message for {symbol}: {e}")

def _on_error(ws, error):
    logging.warning(f"[WS] Error: {error}")

def _on_close(ws, close_status_code, close_msg):
    logging.warning(f"[WS] Closed: {close_status_code} / {close_msg}")

def _on_open(ws):
    logging.info(f"[WS] Connection opened")

def launch_websocket(symbol: str):
    """
    מפעיל WebSocket עבור סמבול בודד (BTCUSDT וכו').
    רצוי להריץ פעם אחת בלבד לכל סמבול.
    """
    if symbol in ws_connections:
        return  # כבר רץ

    def _run():
        url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@trade"
        ws = WebSocketApp(
            url,
            on_message=lambda ws, msg: _on_message(ws, msg, symbol),
            on_error=_on_error,
            on_close=_on_close,
            on_open=_on_open
        )
        ws_connections[symbol] = ws
        ws.run_forever()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

# === מחיר חי (מ־WebSocket או REST fallback) ===
def get_price(symbol: str) -> float:
    """
    מחזיר מחיר חי של סמבול נתון. מנסה קודם WebSocket ואם לא – REST רגיל.
    """
    price = live_prices.get(symbol)
    if price:
        return price

    # fallback ל־REST של Binance
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}"
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        return float(resp.json()["price"])
    except Exception as e:
        logging.warning(f"[Fallback] Failed to fetch REST price for {symbol}: {e}")
        return None






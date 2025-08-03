# utils/ws_fallback.py

import threading
import json
import time
import requests
import logging
from websocket import WebSocketApp
from typing import Dict

# מחירי Live ועדכוני חיבור
live_prices: Dict[str, float] = {}
ws_connections: Dict[str, WebSocketApp] = {}
MAX_CONNECTIONS = 20
PING_INTERVAL = 30

# === WebSocket Events ===
def _on_message(ws, message, symbol):
    try:
        data = json.loads(message)
        price = float(data["p"])
        live_prices[symbol] = price
        logging.debug(f"[WS] {symbol} price updated: {price}")
    except Exception as e:
        logging.warning(f"[WS] Failed to parse message for {symbol}: {e}")

def _on_error(ws, error):
    logging.warning(f"[WS] Error: {error}")

def _on_close(ws, code, reason):
    logging.warning(f"[WS] Closed: {code} / {reason}")

def _on_open(ws):
    logging.info("[WS] Connection opened")

def _run_ws(symbol: str):
    url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@trade"

    def _create_ws():
        return WebSocketApp(
            url,
            on_open=_on_open,
            on_message=lambda ws, msg: _on_message(ws, msg, symbol),
            on_error=_on_error,
            on_close=lambda ws, code, reason: _on_close(ws, code, reason),
        )

    while True:
        if len(ws_connections) >= MAX_CONNECTIONS:
            logging.warning(f"[WS] Max connections ({MAX_CONNECTIONS}) reached. Skipping {symbol}")
            return

        logging.info(f"[WS] Connecting to {symbol}...")
        ws = _create_ws()
        ws_connections[symbol] = ws

        def ping_loop():
            while True:
                try:
                    if ws.sock and ws.sock.connected:
                        ws.send(json.dumps({"method": "PING"}))
                    time.sleep(PING_INTERVAL)
                except Exception as e:
                    logging.warning(f"[WS] Ping error for {symbol}: {e}")
                    break

        ping_thread = threading.Thread(target=ping_loop, daemon=True)
        ping_thread.start()

        try:
            ws.run_forever(ping_interval=PING_INTERVAL)
        except Exception as e:
            logging.warning(f"[WS] run_forever failed for {symbol}: {e}")
        finally:
            time.sleep(5)
            logging.info(f"[WS] Reconnecting to {symbol}...")
            continue

# === Public API ===
def launch_websocket(symbol: str):
    """
    מחבר WebSocket חי לסימבול אחד. אם כבר קיים – לא מתחבר שוב.
    """
    if symbol in ws_connections:
        logging.debug(f"[WS] Already connected to {symbol}")
        return

    thread = threading.Thread(target=_run_ws, args=(symbol,), daemon=True)
    thread.start()

def get_price(symbol: str) -> float:
    """
    מחזיר מחיר חי מסימבול. אם אין WebSocket פעיל, משתמש ב־REST fallback.
    """
    price = live_prices.get(symbol)
    if price:
        return price

    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}"
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        return float(resp.json()["price"])
    except Exception as e:
        logging.warning(f"[Fallback] Failed to fetch REST price for {symbol}: {e}")
        return None






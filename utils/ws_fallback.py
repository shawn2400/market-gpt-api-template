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
ws_status: Dict[str, bool] = {}
MAX_CONNECTIONS = 20
PING_INTERVAL = 30

# === WebSocket Events ===
def _on_message(ws, message, symbol):
    try:
        data = json.loads(message)
        if "p" in data:
            price = float(data["p"])
            live_prices[symbol] = price
            logging.debug(f"[WS] {symbol} price updated: {price}")
        else:
            logging.debug(f"[WS] Received message without 'p': {data}")
    except Exception as e:
        logging.warning(f"[WS] Failed to parse message for {symbol}: {e}")

def _on_error(ws, error):
    logging.warning(f"[WS] Error: {error}")

def _on_close(ws, code, reason):
    logging.warning(f"[WS] Closed: {code} / {reason}")
    # להסיר מהחיבורים (פנוי)
    for sym, w in list(ws_connections.items()):
        if w == ws:
            ws_connections.pop(sym, None)
            ws_status[sym] = False

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
            ws_status[symbol] = False
            return

        logging.info(f"[WS] Connecting to {symbol}...")
        ws = _create_ws()
        ws_connections[symbol] = ws
        ws_status[symbol] = True

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
            # שחרור המשאב כדי לא לתפוס סלוט
            ws_connections.pop(symbol, None)
            ws_status[symbol] = False
            time.sleep(5)
            logging.info(f"[WS] Reconnecting to {symbol}...")

# === Public API ===
def launch_websocket(symbol: str):
    """
    מחבר WebSocket חי לסימבול אחד. אם כבר קיים וחי – לא מתחבר שוב.
    """
    if ws_status.get(symbol, False):
        logging.debug(f"[WS] Already connected to {symbol}")
        return

    thread = threading.Thread(target=_run_ws, args=(symbol,), daemon=True)
    thread.start()

def get_price(symbol: str) -> float:
    """
    מחזיר מחיר חי מסימבול. אם אין WebSocket פעיל, משתמש ב־REST fallback.
    """
    price = live_prices.get(symbol)
    if price is not None:
        return price

    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}"
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        return float(resp.json()["price"])
    except Exception as e:
        logging.warning(f"[Fallback] Failed to fetch REST price for {symbol}: {e}")
        return None

def get_active_ws_symbols():
    """החזר את כל הסימבולים עם WS פעיל (לבדיקה/דאשבורד)."""
    return [sym for sym, active in ws_status.items() if active]










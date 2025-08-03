import threading
import json
import time
import requests
import logging
from websocket import WebSocketApp
from typing import Dict, List

# === חיבורי WS, מחירים חיים, ניהול מצב ===
live_prices: Dict[str, float] = {}
ws_status: Dict[str, bool] = {}
MAX_CONNECTIONS = 1      # חיבור אחד בלבד ב־multi-stream!
PING_INTERVAL = 30

def _on_message_multi(ws, message, symbol_map):
    try:
        data = json.loads(message)
        if "stream" in data and "data" in data:
            stream = data["stream"]
            d = data["data"]
            symbol = stream.split('@')[0].upper()
            if "p" in d:
                price = float(d["p"])
                live_prices[symbol] = price
                logging.debug(f"[WS-MULTI] {symbol} price updated: {price}")
        elif "p" in data and "s" in data:
            symbol = data["s"].upper()
            price = float(data["p"])
            live_prices[symbol] = price
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
    מחבר WebSocket Multi-Stream ל־Binance עבור רשימת סימבולים (trade).
    """
    if ws_status.get("multi", False):
        logging.info("[WS-MULTI] Multi-stream already active")
        return

    # הכנה ל־multi-stream URL
    streams = "/".join([f"{s.lower()}@trade" for s in symbols])
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"
    symbol_map = {f"{s.lower()}@trade": s.upper() for s in symbols}

    def ping_loop(ws):
        while True:
            try:
                if ws.sock and ws.sock.connected:
                    ws.send(json.dumps({"method": "PING"}))
                time.sleep(PING_INTERVAL)
            except Exception as e:
                logging.warning(f"[WS-MULTI] Ping error: {e}")
                break

    def run_ws():
        ws = WebSocketApp(
            url,
            on_open=_on_open,
            on_message=lambda ws, msg: _on_message_multi(ws, msg, symbol_map),
            on_error=_on_error,
            on_close=_on_close,
        )
        ping_thread = threading.Thread(target=ping_loop, args=(ws,), daemon=True)
        ping_thread.start()
        try:
            ws.run_forever(ping_interval=PING_INTERVAL)
        except Exception as e:
            logging.warning(f"[WS-MULTI] run_forever failed: {e}")
        finally:
            ws_status["multi"] = False
            time.sleep(5)
            logging.info("[WS-MULTI] Reconnecting multi-stream...")

    t = threading.Thread(target=run_ws, daemon=True)
    t.start()
    ws_status["multi"] = True

def get_price(symbol: str) -> float:
    """
    מחזיר מחיר חי מסימבול. אם אין WebSocket פעיל, משתמש ב־REST fallback.
    """
    price = live_prices.get(symbol.upper())
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
    """החזר את כל הסימבולים עם WS פעיל (רק למוניטורינג)."""
    if ws_status.get("multi", False):
        return list(live_prices.keys())
    return []










import threading
import json
import time
import requests
import logging
from websocket import WebSocketApp
from typing import Dict, List

live_prices: Dict[str, float] = {}
live_timestamps: Dict[str, float] = {}
ws_status: Dict[str, bool] = {}
MAX_CONNECTIONS = 1      # Multi-stream בלבד

def _on_message_multi(ws, message):
    try:
        data = json.loads(message)
        if "p" in data:
            price = float(data["p"])
            live_prices[symbol] = price
            logging.debug(f"[WS] {symbol} price updated: {price}")
        else:
            logging.debug(f"[WS] Received message without 'p': {data}")
        if "data" in data and "s" in data["data"] and "p" in data["data"]:
            symbol = data["data"]["s"].upper()
            price = float(data["data"]["p"])
            live_prices[symbol] = price
            live_timestamps[symbol] = time.time()
            logging.debug(f"[WS-MULTI] {symbol} price updated: {price}")
        else:
            logging.debug(f"[WS-MULTI] Received: {data}")
 482a0dc2c1505e9f0ec5c361f3d8b43672d6fb04
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

# === Public API ===
def launch_websocket(symbol: str):
    """
    מחבר WebSocket חי לסימבול אחד. אם כבר קיים – לא מתחבר שוב.
    """
    if symbol in ws_connections:
        logging.debug(f"[WS] Already connected to {symbol}")

def launch_multi_websocket(symbols: List[str]):
    if ws_status.get("multi", False):
        logging.info("[WS-MULTI] Multi-stream already active")
 482a0dc2c1505e9f0ec5c361f3d8b43672d6fb04
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
            ws.run_forever(ping_interval=15, ping_timeout=5)
        except Exception as e:
            logging.warning(f"[WS-MULTI] run_forever failed: {e}")
        finally:
            ws_status["multi"] = False
            time.sleep(5)
            logging.info("[WS-MULTI] Reconnecting multi-stream...")
            launch_multi_websocket(symbols)

    t = threading.Thread(target=run_ws, daemon=True)
    t.start()
    ws_status["multi"] = True

def is_price_fresh(symbol: str, max_age_sec: int = 5) -> bool:
    now = time.time()
    ts = live_timestamps.get(symbol.upper())
    return ts is not None and (now - ts) < max_age_sec

def get_book_ticker(symbol: str):
    try:
        url = f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={symbol.upper()}"
        resp = requests.get(url, timeout=2)
        resp.raise_for_status()
        data = resp.json()
        return float(data["bidPrice"]), float(data["askPrice"])
    except Exception as e:
        logging.warning(f"[Fallback] Failed to fetch bookTicker for {symbol}: {e}")
        return None, None

def get_price(symbol: str, max_age_sec: int = 5) -> float:
    # נסה קודם WS טרי
    symbol = symbol.upper()
    if is_price_fresh(symbol, max_age_sec=max_age_sec):
        return live_prices.get(symbol)
    # Fallback ל־bookTicker (ממוצע bid/ask)
    bid, ask = get_book_ticker(symbol)
    if bid and ask:
        return round((bid + ask) / 2, 6)
    # אחרון – REST last price (לא מומלץ)
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        resp = requests.get(url, timeout=2)
        resp.raise_for_status()
        return float(resp.json()["price"])
    except Exception as e:
        logging.warning(f"[Fallback] Failed to fetch REST price for {symbol}: {e}")
        return None


















>>>>>>> 482a0dc2c1505e9f0ec5c361f3d8b43672d6fb04

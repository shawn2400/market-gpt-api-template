# utils/ws_fallback.py

import threading
import time
import json
import logging
import requests
from collections import defaultdict
from websocket import WebSocketApp
from binance.client import Client
from dotenv import load_dotenv
import os

load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
MARKET_TYPE = os.getenv("MARKET_TYPE", "futures")  # אפשר גם spot

# REST fallback client
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

# חיבורי WS חיים
_ws_connections = {}
_ws_prices = defaultdict(lambda: None)
_ws_last_ping = {}

# הגבלת חיבורים במקביל
MAX_WS_CONNECTIONS = 20

# ===========================================================
def _futures_ws_url(symbol):
    return f"wss://fstream.binance.com/ws/{symbol.lower()}@ticker"

def _spot_ws_url(symbol):
    return f"wss://stream.binance.com:9443/ws/{symbol.lower()}@ticker"

def _get_ws_url(symbol):
    if MARKET_TYPE == "spot":
        return _spot_ws_url(symbol)
    return _futures_ws_url(symbol)

def _get_rest_price(symbol):
    try:
<<<<<<< HEAD
        data = json.loads(message)
 HEAD
        if "p" in data:
            price = float(data["p"])
            live_prices[symbol] = price
            logging.debug(f"[WS] {symbol} price updated: {price}")
        else:
            logging.debug(f"[WS] Received message without 'p': {data}")
=======
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

 HEAD
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
=======
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
=======
        if MARKET_TYPE == "spot":
            ticker = client.get_symbol_ticker(symbol=symbol)
            return float(ticker["price"])
        else:
            ticker = client.futures_symbol_ticker(symbol=symbol)
            return float(ticker["price"])
    except Exception as e:
        logging.warning(f"[ws_fallback] REST price error for {symbol}: {e}")
>>>>>>> 8de339e6f1092585be16d7a6ec1f7effb0657cab
        return None

def _on_message(ws, message, symbol):
    try:
        data = json.loads(message)
        price = None
        # מחיר tick רגיל (p) בפיוצ'רס
        if "p" in data:
            price = float(data["p"])
        # פותח גם ל-spot (c=close)
        elif "c" in data:
            price = float(data["c"])
        if price:
            _ws_prices[symbol] = price
    except Exception as e:
        logging.warning(f"[ws_fallback] Message error ({symbol}): {e}")

def _on_error(ws, error, symbol):
    logging.error(f"[ws_fallback] WebSocket error ({symbol}): {error}")

def _on_close(ws, close_status_code, close_msg, symbol):
    logging.warning(f"[ws_fallback] WS closed ({symbol}): {close_status_code} {close_msg}")
    # נסה להתחבר מחדש אחרי 5 שניות
    time.sleep(5)
    launch_websocket(symbol, force=True)

def _on_open(ws, symbol):
    logging.info(f"[ws_fallback] WS opened for {symbol}")
    _ws_last_ping[symbol] = time.time()

def _ping_forever(ws, symbol):
    while True:
        try:
            time.sleep(30)
            if ws.sock and ws.sock.connected:
                ws.send(json.dumps({"method": "PING"}))
                _ws_last_ping[symbol] = time.time()
        except Exception as e:
            logging.warning(f"[ws_fallback] Ping error ({symbol}): {e}")
            break

def launch_websocket(symbol, force=False):
    symbol = symbol.upper()
    if not force and symbol in _ws_connections and _ws_connections[symbol].sock and _ws_connections[symbol].sock.connected:
        logging.info(f"[ws_fallback] WS for {symbol} already running")
        return

    if len(_ws_connections) >= MAX_WS_CONNECTIONS:
        logging.warning(f"[ws_fallback] Max connections ({MAX_WS_CONNECTIONS}) reached. Skipping {symbol}")
        return

    ws_url = _get_ws_url(symbol)

    def _run():
        ws = WebSocketApp(
            ws_url,
            on_open=lambda ws: _on_open(ws, symbol),
            on_message=lambda ws, msg: _on_message(ws, msg, symbol),
            on_error=lambda ws, err: _on_error(ws, err, symbol),
            on_close=lambda ws, code, msg: _on_close(ws, code, msg, symbol)
        )
        _ws_connections[symbol] = ws
        ping_thread = threading.Thread(target=_ping_forever, args=(ws, symbol), daemon=True)
        ping_thread.start()
        ws.run_forever(ping_interval=20, ping_timeout=10)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    logging.info(f"[ws_fallback] WS thread launched for {symbol}")

def launch_multi_websocket(symbols):
    # מחובר כל סמל ברשימה עד למקסימום מותר
    count = 0
    for symbol in symbols:
        if count >= MAX_WS_CONNECTIONS:
            logging.warning(f"[ws_fallback] Max WS connections reached. Skipping {symbol}")
            break
        launch_websocket(symbol)
        count += 1

def get_price(symbol):
    """החזר מחיר חי – קודם WS, אם אין – REST"""
    symbol = symbol.upper()
    price = _ws_prices.get(symbol)
    if price:
        return price
    return _get_rest_price(symbol)









<<<<<<< HEAD
 HEAD
=======
=======
>>>>>>> 8de339e6f1092585be16d7a6ec1f7effb0657cab










 482a0dc2c1505e9f0ec5c361f3d8b43672d6fb04

import threading
import json
import time
import requests
import logging
from websocket import WebSocketApp
from typing import Dict, List

live_prices: Dict[str, float] = {}
multi_ws: WebSocketApp = None
stream_symbols: List[str] = []
PING_INTERVAL = 30

def _build_stream_url(symbols: List[str]) -> str:
    streams = '/'.join(f"{s.lower()}@trade" for s in symbols)
    return f"wss://stream.binance.com:9443/stream?streams={streams}"

def _on_message(ws, message):
    try:
        msg = json.loads(message)
        data = msg.get("data", {})
        symbol = data.get("s")
        price = data.get("p")
        if symbol and price:
            live_prices[symbol] = float(price)
            logging.debug(f"[WS-MULTI] {symbol} price updated: {price}")
        else:
            logging.debug(f"[WS-MULTI] Message missing data: {msg}")
    except Exception as e:
        logging.warning(f"[WS-MULTI] Failed to parse message: {e}")

def _on_error(ws, error):
    logging.warning(f"[WS-MULTI] Error: {error}")

def _on_close(ws, code, reason):
    logging.warning(f"[WS-MULTI] Closed: {code} / {reason}")

def _on_open(ws):
    logging.info("[WS-MULTI] Connection opened")

def _run_multi_ws(symbols: List[str]):
    global multi_ws
    url = _build_stream_url(symbols)
    multi_ws = WebSocketApp(
        url,
        on_open=_on_open,
        on_message=_on_message,
        on_error=_on_error,
        on_close=_on_close,
    )

    def ping_loop():
        while True:
            try:
                if multi_ws.sock and multi_ws.sock.connected:
                    multi_ws.send(json.dumps({"method": "PING"}))
                time.sleep(PING_INTERVAL)
            except Exception as e:
                logging.warning(f"[WS-MULTI] Ping error: {e}")
                break

    ping_thread = threading.Thread(target=ping_loop, daemon=True)
    ping_thread.start()

    while True:
        try:
            logging.info("[WS-MULTI] Connecting multi-stream WebSocket...")
            multi_ws.run_forever(ping_interval=PING_INTERVAL)
        except Exception as e:
            logging.warning(f"[WS-MULTI] run_forever failed: {e}")
        finally:
            time.sleep(5)
            logging.info("[WS-MULTI] Reconnecting...")

def launch_multi_websocket(symbols: List[str]):
    """הפעל WebSocket יחיד לכל הסימבולים."""
    global stream_symbols
    if not symbols:
        raise ValueError("symbols list is empty")
    stream_symbols = [s.upper() for s in symbols]
    t = threading.Thread(target=_run_multi_ws, args=(stream_symbols,), daemon=True)
    t.start()

def get_price(symbol: str) -> float:
    """מחזיר מחיר חי מסימבול. אם אין WS או מחיר – מנסה REST."""
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
    """החזר את כל הסימבולים עם WS פעיל (לבדיקה/דאשבורד)."""
    return list(live_prices.keys())










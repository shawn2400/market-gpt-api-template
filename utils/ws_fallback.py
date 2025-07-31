# ✅ utils/ws_fallback.py

import threading
import time
import json
import websocket
import requests

_ws_data = {}
_ws_threads = {}
_rest_fallback_ttl = 20  # שניות בין קריאות REST במקרה כשל
_last_rest_call = {}

BINANCE_WS_URL = "wss://fstream.binance.com/ws"
BINANCE_REST_URL = "https://fapi.binance.com/fapi/v1/ticker/price?symbol={}"

def _on_message(ws, message, symbol):
    try:
        data = json.loads(message)
        if "p" in data:
            _ws_data[symbol] = float(data["p"])
    except Exception as e:
        print(f"[ws_fallback] שגיאה בפיענוח הודעה: {e}")

def _on_error(ws, error):
    print(f"[ws_fallback] WebSocket Error: {error}")

def _on_close(ws, close_status_code, close_msg):
    print(f"[ws_fallback] חיבור נסגר – קוד: {close_status_code}, הודעה: {close_msg}")

def _ws_run(symbol):
    try:
        url = f"{BINANCE_WS_URL}/{symbol.lower()}@trade"
        ws = websocket.WebSocketApp(
            url,
            on_message=lambda ws, msg: _on_message(ws, msg, symbol),
            on_error=_on_error,
            on_close=_on_close
        )
        ws.run_forever()
    except Exception as e:
        print(f"[ws_fallback] כשל בחיבור ל־WebSocket עבור {symbol}: {e}")

def launch_websocket(symbol):
    symbol = symbol.upper()
    if symbol not in _ws_threads:
        thread = threading.Thread(target=_ws_run, args=(symbol,), daemon=True)
        _ws_threads[symbol] = thread
        thread.start()

def get_price(symbol: str) -> float:
    symbol = symbol.upper()
    price = _ws_data.get(symbol)
    if price:
        return price

    now = time.time()
    last_call = _last_rest_call.get(symbol, 0)
    if now - last_call < _rest_fallback_ttl:
        return None

    try:
        res = requests.get(BINANCE_REST_URL.format(symbol), timeout=2)
        res.raise_for_status()
        data = res.json()
        price = float(data["price"])
        _last_rest_call[symbol] = now
        return price
    except Exception as e:
        print(f"[ws_fallback] ❌ REST fallback נכשל עבור {symbol}: {e}")
        return None





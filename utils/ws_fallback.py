# utils/ws_fallback.py

import threading
import time
import json
import requests
from websocket import WebSocketApp

PRICE_CACHE = {}
WS_THREADS = {}

def get_price(symbol: str) -> float:
    """שולף מחיר חי מה־cache או מבצע fallback ל־REST אם אין מידע"""
    sym = symbol.lower()
    if sym in PRICE_CACHE:
        return PRICE_CACHE[sym]
    try:
        url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol.upper()}"
        res = requests.get(url, timeout=5)
        if res.ok:
            return float(res.json()["price"])
    except Exception as e:
        print(f"[Fallback] שגיאה ב־REST: {e}")
    return 0.0

def _on_message(ws, msg, symbol):
    try:
        data = json.loads(msg)
        PRICE_CACHE[symbol.lower()] = float(data["p"])
    except Exception as e:
        print(f"[WebSocket] שגיאה בפרמוס: {e}")

def _on_error(ws, err):
    print(f"[WebSocket] שגיאה: {err}")

def _on_close(ws, code, reason):
    print(f"[WebSocket] נסגר: {code} / {reason}")

def _run_ws(symbol: str):
    stream = symbol.lower() + "@ticker"
    url = f"wss://fstream.binance.com/ws/{stream}"
    ws = WebSocketApp(
        url,
        on_message=lambda ws, msg: _on_message(ws, msg, symbol),
        on_error=_on_error,
        on_close=_on_close,
    )
    try:
        ws.run_forever()
    except Exception as e:
        print(f"[WebSocket] כשל: {e}")

def launch_websocket(symbol: str):
    if symbol.lower() in WS_THREADS:
        return
    t = threading.Thread(target=_run_ws, args=(symbol,), daemon=True)
    WS_THREADS[symbol.lower()] = t
    t.start()



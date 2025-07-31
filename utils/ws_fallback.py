# utils/ws_fallback.py

import threading
import json
import requests
import websocket

live_prices = {}
ws_connected = False

def on_message(ws, message):
    try:
        data = json.loads(message)
        if "s" in data and "c" in data:
            symbol = data["s"]
            price = float(data["c"])
            live_prices[symbol] = price
    except Exception:
        pass

def on_error(ws, error):
    global ws_connected
    ws_connected = False

def on_close(ws, *_):
    global ws_connected
    ws_connected = False

def on_open(ws):
    global ws_connected
    ws_connected = True

def launch_websocket(symbol="BTCUSDT"):
    def run():
        while True:
            try:
                ws = websocket.WebSocketApp(
                    f"wss://stream.binance.com:9443/ws/{symbol.lower()}@ticker",
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                    on_open=on_open,
                )
                ws.run_forever()
            except Exception:
                import time
                time.sleep(5)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

def get_price(symbol: str) -> float:
    # נסה WebSocket קודם
    price = live_prices.get(symbol.upper())
    if price:
        return price

    # fallback ל־Binance REST
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}"
        response = requests.get(url, timeout=3)
        if response.ok:
            return float(response.json()["price"])
    except Exception:
        return None





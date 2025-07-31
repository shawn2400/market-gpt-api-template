# utils/ws_fallback.py
import threading
import time
import json
from binance import ThreadedWebsocketManager
from utils.binance_client import client

prices = {}
ws_running = {}

def launch_websocket(symbol: str):
    """
    מפעיל WebSocket חי למחיר של סמל נתון.
    שומר את המחיר האחרון במילון prices.
    """
    if ws_running.get(symbol):
        return

    def handle_socket(msg):
        if msg.get("e") == "error":
            print(f"[WebSocket] שגיאה עבור {symbol}: {msg}")
            return
        try:
            prices[symbol] = float(msg["c"])
        except Exception as e:
            print(f"[WebSocket] שגיאה בעיבוד מחיר {symbol}: {e}")

    def run_ws():
        try:
            twm = ThreadedWebsocketManager(api_key=client.API_KEY, api_secret=client.API_SECRET)
            twm.start()
            twm.start_symbol_ticker_socket(callback=handle_socket, symbol=symbol)
            ws_running[symbol] = True
            while ws_running.get(symbol, False):
                time.sleep(5)
        except Exception as e:
            print(f"[WebSocket] נכשל עבור {symbol}: {e}")
        finally:
            ws_running[symbol] = False

    threading.Thread(target=run_ws, daemon=True).start()

def get_price(symbol: str, market_type: str = "futures") -> float:
    """
    מנסה להחזיר מחיר חי מה־WebSocket.
    אם נכשל – עובר ל־REST רגיל (fallback).
    """
    price = prices.get(symbol)
    if price:
        return price

    try:
        if market_type == "futures":
            res = client.futures_symbol_ticker(symbol=symbol)
        else:
            res = client.get_symbol_ticker(symbol=symbol)
        return float(res["price"])
    except Exception as e:
        print(f"[Fallback REST] שגיאה בשליפת מחיר {symbol}: {e}")
        return None


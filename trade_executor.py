# trade_executor.py
import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET").encode()
BASE_URL = "https://18.162.221.196"  # IP ישיר
HOST_HEADER = {"Host": "fapi.binance.com"}

def sign_request(params):
    query_string = urlencode(params)
    signature = hmac.new(API_SECRET, query_string.encode(), hashlib.sha256).hexdigest()
    return f"{query_string}&signature={signature}"

def send_signed_request(http_method, endpoint, payload=None):
    url = f"{BASE_URL}{endpoint}"
    headers = {
        "X-MBX-APIKEY": API_KEY,
        **HOST_HEADER
    }
    payload = payload or {}
    payload["timestamp"] = int(time.time() * 1000)
    signed = sign_request(payload)

    if http_method == "POST":
        return requests.post(url, headers=headers, data=signed, timeout=10)
    elif http_method == "GET":
        return requests.get(f"{url}?{signed}", headers=headers, timeout=10)

def execute_trade_live(symbol, entry_price, stop_price, tp_price, side, leverage=20):
    try:
        send_signed_request("POST", "/fapi/v1/leverage", {
            "symbol": symbol,
            "leverage": leverage
        })

        side_binance = "BUY" if side.upper() == "LONG" else "SELL"
        opposite_side = "SELL" if side_binance == "BUY" else "BUY"

        qty = round(10 / entry_price, 3)  # לדוגמה

        order = send_signed_request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": side_binance,
            "type": "MARKET",
            "quantity": qty
        }).json()

        time.sleep(1)

        send_signed_request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": opposite_side,
            "type": "STOP_MARKET",
            "stopPrice": round(stop_price, 2),
            "closePosition": "true"
        })

        time.sleep(1)

        send_signed_request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": opposite_side,
            "type": "LIMIT",
            "price": round(tp_price, 2),
            "timeInForce": "GTC",
            "closePosition": "true"
        })

        return {"status": "ok", "symbol": symbol, "qty": qty, "entry": entry_price}
    except Exception as e:
        return {"status": "error", "message": str(e)}







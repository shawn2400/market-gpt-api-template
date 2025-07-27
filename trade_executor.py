# trade_executor.py
import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv
from utils.quantity_utils import calculate_quantity

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET").encode()
BASE_URL = "https://fapi.binance.com"
HOST_HEADER = {}  # אין צורך ב־Host אם אתה משתמש ב־URL המקורי

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

    try:
        if http_method == "POST":
            response = requests.post(url, headers=headers, data=signed, timeout=10)
        elif http_method == "GET":
            response = requests.get(f"{url}?{signed}", headers=headers, timeout=10)
        else:
            raise ValueError("Unsupported HTTP method")

        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        print(f"[!] שגיאה בבקשת {endpoint}: {e}")
        raise

def execute_trade_live(symbol, entry_price, stop_price, tp_price, side, leverage=20, budget_usd=100):
    try:
        # ⚙️ שינוי מינוף
        send_signed_request("POST", "/fapi/v1/leverage", {
            "symbol": symbol,
            "leverage": leverage
        })

        side_binance = "BUY" if side.upper() == "LONG" else "SELL"
        opposite_side = "SELL" if side_binance == "BUY" else "BUY"

        qty = calculate_quantity(budget_usd, entry_price, leverage)

        # 🟢 כניסה לטרייד
        order = send_signed_request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": side_binance,
            "type": "MARKET",
            "quantity": qty
        }).json()

        time.sleep(1)

        # 🔴 Stop Loss
        send_signed_request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": opposite_side,
            "type": "STOP_MARKET",
            "stopPrice": round(stop_price, 2),
            "closePosition": "true"
        })

        time.sleep(1)

        # 🟢 Take Profit
        send_signed_request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": opposite_side,
            "type": "LIMIT",
            "price": round(tp_price, 2),
            "timeInForce": "GTC",
            "closePosition": "true"
        })

        print(f"✅ טרייד נשלח בהצלחה: {symbol} | כמות: {qty}")
        return {"status": "ok", "symbol": symbol, "qty": qty, "entry": entry_price}
    except Exception as e:
        print(f"[!] שגיאה בביצוע טרייד ל־{symbol}: {e}")
        return {"status": "error", "message": str(e)}








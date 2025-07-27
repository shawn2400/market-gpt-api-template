import requests
import os
import time

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

# ✅ כתובת IP ישירה של Binance Futures (נכון לכרגע)
BINANCE_FUTURES_IP = "https://18.162.221.196"
HOST_HEADER = {"Host": "fapi.binance.com"}

def scan_all_futures():
    try:
        url = f"{BINANCE_FUTURES_IP}/fapi/v1/ticker/price"
        headers = {
            "X-MBX-APIKEY": API_KEY,
            **HOST_HEADER
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # הדמיית תוצאה פשוטה רק לשם בדיקה
        results = []
        for item in data:
            symbol = item["symbol"]
            price = float(item["price"])
            if "USDT" in symbol and not symbol.endswith("DOWNUSDT") and not symbol.endswith("UPUSDT"):
                if price > 0:  # תנאי סינון דמה
                    results.append({
                        "symbol": symbol,
                        "price": price
                    })

        return results

    except Exception as e:
        raise Exception(f"בעיה בגישה ל־Binance Futures: {str(e)}")





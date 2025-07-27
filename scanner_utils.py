import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
BASE_URL = "https://18.162.221.196"  # IP ישיר
HOST_HEADER = {"Host": "fapi.binance.com"}

def scan_all_futures():
    try:
        url = f"{BASE_URL}/fapi/v1/ticker/price"
        headers = {
            "X-MBX-APIKEY": API_KEY,
            **HOST_HEADER
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data:
            symbol = item["symbol"]
            price = float(item["price"])

            if "USDT" in symbol and not any(x in symbol for x in ["DOWN", "UP", "BULL", "BEAR"]):
                results.append({
                    "symbol": symbol,
                    "price": price
                })

        return results

    except Exception as e:
        raise Exception(f"שגיאה בסריקה מ-Binance: {str(e)}")





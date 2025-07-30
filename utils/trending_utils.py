# ===== קובץ: utils/trending_utils.py =====

import requests

def get_trending_symbols():
    """
    מחזיר רשימת סימבולים בולטים ב־CoinGecko (USDT בלבד).
    """
    try:
        url = "https://api.coingecko.com/api/v3/search/trending"
        resp = requests.get(url, timeout=6)
        data = resp.json()
        trending = []
        for coin in data["coins"]:
            symbol = coin["item"]["symbol"].upper() + "USDT"
            trending.append(symbol)
        return trending
    except Exception as e:
        print(f"[Trending] שגיאה בשליפת Trending: {e}")
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

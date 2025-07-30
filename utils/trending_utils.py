# utils/trending_utils.py
# פונקציות לשאיבת סמלים טרנדים מ־CoinGecko

from typing import Optional, List
import requests

COINGECKO_API = "https://api.coingecko.com/api/v3/search/trending"

# מיפוי חלקי לשמות סמלים פופולריים
symbol_mapping = {
    "btc": "BTCUSDT",
    "eth": "ETHUSDT",
    "bnb": "BNBUSDT",
    "sol": "SOLUSDT",
    "doge": "DOGEUSDT",
    "shib": "SHIBUSDT",
    "matic": "MATICUSDT",
    "avax": "AVAXUSDT",
    "ltc": "LTCUSDT",
    "xrp": "XRPUSDT",
    "link": "LINKUSDT",
    "ada": "ADAUSDT",
    "uni": "UNIUSDT",
    "pepe": "PEPEUSDT",
    "ton": "TONUSDT",
    "inj": "INJUSDT",
    "op": "OPUSDT",
    "rndr": "RNDRUSDT",
    "tia": "TIAUSDT",
    "floki": "FLOKIUSDT",
    "grt": "GRTUSDT"
}

def get_trending_symbols(
    trending_source: Optional[str] = "coingecko",
    market_type: str = "spot"
) -> List[str]:
    """
    מחזיר רשימת סמלים טרנדים לפי מקור מוגדר (כעת רק CoinGecko נתמך).
    תומך ב־spot/futures/grid לפי סוג השוק.
    """
    if trending_source.lower() != "coingecko":
        return []

    try:
        response = requests.get(COINGECKO_API, timeout=5)
        response.raise_for_status()
        data = response.json()

        coins = data.get("coins", [])
        trending = []

        for coin in coins:
            item = coin.get("item", {})
            symbol = item.get("symbol", "").lower()
            mapped = symbol_mapping.get(symbol)
            if mapped:
                trending.append(mapped)

        return trending or ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

    except Exception:
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]























































































































































































































































































































































































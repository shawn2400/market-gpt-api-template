# utils/trending_utils.py — ייבוא מגורמי Trending חיצוניים

import requests, os

def get_trending_symbols(source="coingecko", market_types=("futures",)):
    """
    מחזיר רשימת סמלים trending מ‑CoinGecko או CoinMarketCap
    """
    try:
        if source=="coingecko":
            url="https://api.coingecko.com/api/v3/search/trending"
            data=requests.get(url,timeout=5).json()
            return [item["item"]["symbol"].upper()+"USDT" for item in data.get("coins",[])]
        # אם תרצה להוסיף CoinMarketCap – כאן המקום.
        return []
    except:
        return []


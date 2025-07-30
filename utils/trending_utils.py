import requests
import logging
from utils.binance_client import client

def get_all_binance_symbols(market_type="futures"):
    """מחזיר סט של כל הסמלים הפעילים בביננס."""
    try:
        if market_type == "futures":
            info = client.futures_exchange_info()
        else:
            info = client.get_exchange_info()
        return set([
            x['symbol'] for x in info['symbols']
            if x['quoteAsset'] == 'USDT' and x['status'] == 'TRADING'
        ])
    except Exception as e:
        logging.warning(f"[trending_utils] שגיאה בשליפת סמלים מ-Binance: {e}")
        return set()

def get_trending_symbols(
    trending_source="coingecko",
    market_type="futures",
    fallback_default=True
):
    """
    Trending מ־CoinGecko (ברירת מחדל) – אפשר להרחיב ל־CMC בקלות.
    trending_source: "coingecko" / "coinmarketcap"
    market_type: "futures" / "spot" (רק סמלים חוקיים לזירת מסחר)
    fallback_default: להחזיר TOP אם אין trending
    """
    try:
        if trending_source == "coingecko":
            url = "https://api.coingecko.com/api/v3/search/trending"
            resp = requests.get(url, timeout=8)
            data = resp.json()
            trending = []
            for coin in data["coins"]:
                symbol = coin["item"]["symbol"].upper()
                binance_symbol = f"{symbol}USDT"
                trending.append(binance_symbol)
            trending = list(dict.fromkeys(trending))
        elif trending_source == "coinmarketcap":
            # אופציונלי – דורש API KEY, תוכל לשלב לפי הדוקומנטציה של CMC
            # api_key = os.getenv("COINMARKETCAP_API_KEY")
            # url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/trending/latest"
            # resp = requests.get(url, headers={"X-CMC_PRO_API_KEY": api_key})
            # data = resp.json()
            # trending = [item['symbol'] + "USDT" for item in data['data']]
            trending = []  # להשלים אם תשלב CMC
        else:
            trending = []

        # סינון רק מה שבאמת סחיר בביננס (פיוצ'רס/ספוט)
        binance_symbols = get_all_binance_symbols(market_type)
        filtered = [s for s in trending if s in binance_symbols]

        # ברירת מחדל אם כלום לא חזר
        if not filtered and fallback_default:
            filtered = [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
                "OPUSDT", "ARBUSDT", "PEPEUSDT", "DOGEUSDT"
            ]
        return filtered
    except Exception as e:
        logging.warning(f"[trending_utils] שגיאה בשליפת Trending: {e}")
        if fallback_default:
            return [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
                "OPUSDT", "ARBUSDT", "PEPEUSDT", "DOGEUSDT"
            ]
        return []


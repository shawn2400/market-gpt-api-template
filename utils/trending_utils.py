# utils/trending_utils.py
# שאיבת סמלים טרנדיים ממקורות שונים (CoinGecko, Binance Trending, LunarCrush)
import requests
import os
import logging
import time
from typing import Optional, List, Dict

COINGECKO_API = "https://api.coingecko.com/api/v3/search/trending"
COINGECKO_MARKET_API = "https://api.coingecko.com/api/v3/coins/markets"
BINANCE_TRENDING_API = "https://www.binance.com/bapi/asset/v1/public/asset-service/product/get-trending"
LUNARCRUSH_TRENDING_API = "https://api.lunarcrush.com/v2?data=assets&sort=galaxy_score&limit=20"
LUNARCRUSH_API_KEY = os.getenv("LUNARCRUSH_API_KEY")

# --- זיכרון cache (רק לזמן ריצה)
_cache: Dict[str, tuple[List[str], float]] = {}
CACHE_TTL = 600  # 10 דקות

def _cached(key: str) -> tuple[List[str], float]:
    return _cache.get(key, ([], 0))

def _store_cache(key: str, value: List[str]) -> None:
    _cache[key] = (value, time.time())

# מיפוי טיקר → סימבול ביננס (ל־Futures, אפשר להרחיב)
symbol_mapping: Dict[str, Dict[str, str]] = {
    "btc": {"symbol": "BTCUSDT", "market": "futures"},
    "eth": {"symbol": "ETHUSDT", "market": "futures"},
    "bnb": {"symbol": "BNBUSDT", "market": "futures"},
    "sol": {"symbol": "SOLUSDT", "market": "futures"},
    "doge": {"symbol": "DOGEUSDT", "market": "futures"},
    "shib": {"symbol": "SHIBUSDT", "market": "futures"},
    "matic": {"symbol": "MATICUSDT", "market": "futures"},
    "avax": {"symbol": "AVAXUSDT", "market": "futures"},
    "ltc": {"symbol": "LTCUSDT", "market": "futures"},
    "xrp": {"symbol": "XRPUSDT", "market": "futures"},
    "link": {"symbol": "LINKUSDT", "market": "futures"},
    "ada": {"symbol": "ADAUSDT", "market": "futures"},
    "uni": {"symbol": "UNIUSDT", "market": "futures"},
    "pepe": {"symbol": "PEPEUSDT", "market": "futures"},
    "ton": {"symbol": "TONUSDT", "market": "futures"},
    "inj": {"symbol": "INJUSDT", "market": "futures"},
    "op": {"symbol": "OPUSDT", "market": "futures"},
    "rndr": {"symbol": "RNDRUSDT", "market": "futures"},
    "tia": {"symbol": "TIAUSDT", "market": "futures"},
    "floki": {"symbol": "FLOKIUSDT", "market": "futures"},
    "grt": {"symbol": "GRTUSDT", "market": "futures"},
    "arb": {"symbol": "ARBUSDT", "market": "futures"},
    "blur": {"symbol": "BLURUSDT", "market": "futures"},
    "apt": {"symbol": "APTUSDT", "market": "futures"},
    "lina": {"symbol": "LINAUSDT", "market": "futures"},
    "cake": {"symbol": "CAKEUSDT", "market": "futures"},
    "chz": {"symbol": "CHZUSDT", "market": "futures"},
    "stx": {"symbol": "STXUSDT", "market": "futures"},
    "near": {"symbol": "NEARUSDT", "market": "futures"},
    "fil": {"symbol": "FILUSDT", "market": "futures"}
}

def get_trending_symbols(
    trending_source: Optional[str] = "coingecko",
    market_type: str = "spot",
    min_volume: Optional[float] = None,
    volume_lookup: Optional[Dict[str, float]] = None,
    top: Optional[int] = None,
    min_change_percent: Optional[float] = None
) -> List[str]:
    """
    מחזיר רשימת סמלים טרנדיים ממקור שנבחר (coingecko, binance, lunarcrush)
    """
    if not trending_source:
        logging.warning("⚠️ trending_source ריק – שימוש בברירת מחדל 'coingecko'")
        trending_source = "coingecko"
    if not market_type:
        market_type = "spot"

    trending_source = trending_source.lower()
    market_type = market_type.lower()
    base_market = "futures" if market_type == "grid" else market_type

    cache_key = f"{trending_source}:{base_market}:{min_volume}:{top}:{min_change_percent}"
    symbols, timestamp = _cached(cache_key)
    if symbols and (time.time() - timestamp < CACHE_TTL):
        return symbols

    try:
        symbols = []

        if trending_source == "coingecko":
            trending_resp = requests.get(COINGECKO_API, timeout=5)
            trending_resp.raise_for_status()
            trending_data = trending_resp.json()
            trending_ids = [c['item']['id'] for c in trending_data.get("coins", [])]

            market_resp = requests.get(COINGECKO_MARKET_API, params={
                "vs_currency": "usd",
                "ids": ','.join(trending_ids),
                "price_change_percentage": "24h"
            }, timeout=5)
            market_resp.raise_for_status()
            market_data = market_resp.json()

            for coin in market_data:
                symbol = coin.get("symbol", "").lower()
                change = coin.get("price_change_percentage_24h", 0.0)
                mapped = symbol_mapping.get(symbol)
                if mapped and mapped.get("market") == base_market:
                    if min_change_percent is None or change >= min_change_percent:
                        symbols.append(mapped["symbol"])

        elif trending_source == "binance":
            response = requests.get(BINANCE_TRENDING_API, timeout=5)
            response.raise_for_status()
            data = response.json()
            articles = data.get("data", {}).get("articles", [])
            for article in articles:
                title = article.get("title", "").lower()
                for key, info in symbol_mapping.items():
                    if key in title and info.get("market") == base_market:
                        symbols.append(info["symbol"])

        elif trending_source == "lunarcrush":
            if not LUNARCRUSH_API_KEY:
                logging.warning("⚠️ חסר מפתח API עבור LunarCrush – דילוג")
                return []
            url = f"{LUNARCRUSH_TRENDING_API}&key={LUNARCRUSH_API_KEY}"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            assets = data.get("data", [])
            for asset in assets:
                symbol = asset.get("symbol", "").lower()
                mapped = symbol_mapping.get(symbol)
                if mapped and mapped.get("market") == base_market:
                    symbols.append(mapped["symbol"])

        # סינון לפי נפח אם זמין
        if min_volume is not None and volume_lookup is not None:
            symbols = [s for s in symbols if volume_lookup.get(s, 0) >= min_volume]

        # הגבלת מספר תוצאות
        if top is not None and len(symbols) > top:
            symbols = symbols[:top]

        # אחסון cache בזיכרון
        result = symbols or ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
        _store_cache(cache_key, result)
        return result

    except Exception as e:
        logging.error(f"שגיאה בשליפת טרנדים מ-{trending_source}: {type(e).__name__} – {e}")
        # Fallback אם הכל נכשל
        _store_cache(cache_key, ["BTCUSDT", "ETHUSDT", "BNBUSDT"])
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

def get_combined_trending_symbols(
    market_type: str = "futures",
    min_volume: Optional[float] = None,
    volume_lookup: Optional[Dict[str, float]] = None,
    sources: List[str] = ["coingecko", "binance", "lunarcrush"],
    top: Optional[int] = None,
    min_change_percent: Optional[float] = None
) -> List[str]:
    """
    מחזיר רשימה מאוחדת של trending מכל המקורות (unique)
    """
    combined: List[str] = []
    for source in sources:
        try:
            combined.extend(
                get_trending_symbols(
                    trending_source=source,
                    market_type=market_type,
                    min_volume=min_volume,
                    volume_lookup=volume_lookup,
                    top=top,
                    min_change_percent=min_change_percent
                )
            )
        except Exception as e:
            logging.warning(f"⚠️ מקור {source} נכשל: {e}")
    # מחזיר רשימה ייחודית וממוינת
    return sorted(list(set(combined)))

if __name__ == "__main__":
    print("Trending (CoinGecko):", get_trending_symbols("coingecko", market_type="futures", top=5))
    print("Trending (Binance):", get_trending_symbols("binance", market_type="futures", top=5))
    print("Combined Trending:", get_combined_trending_symbols(market_type="futures", top=7))





























































































































































































































































































































































































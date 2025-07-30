# utils/trending_utils.py
# פונקציות לשאיבת סמלים טרנדים מ־CoinGecko, Binance Trending, LunarCrush ועוד

from typing import Optional, List, Dict
import requests
import os

COINGECKO_API = "https://api.coingecko.com/api/v3/search/trending"
BINANCE_TRENDING_API = "https://www.binance.com/bapi/asset/v1/public/asset-service/product/get-trending"
LUNARCRUSH_TRENDING_API = "https://api.lunarcrush.com/v2?data=assets&sort=galaxy_score&limit=20"

LUNARCRUSH_API_KEY = os.getenv("LUNARCRUSH_API_KEY")

# מיפוי חלקי לשמות סמלים פופולריים כולל מידע על שוק
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
    volume_lookup: Optional[Dict[str, float]] = None
) -> List[str]:
    """
    מחזיר רשימת סמלים טרנדים לפי מקור מוגדר (coingecko, binance, lunarcrush).
    תומך ב־spot/futures/grid לפי סוג השוק.
    מאפשר גם סינון לפי נפח מסחר במידת הצורך.
    """
    trending_source = trending_source.lower()
    market_type = market_type.lower()

    try:
        symbols = []

        if trending_source == "coingecko":
            response = requests.get(COINGECKO_API, timeout=5)
            response.raise_for_status()
            data = response.json()
            coins = data.get("coins", [])
            for coin in coins:
                item = coin.get("item", {})
                symbol = item.get("symbol", "").lower()
                mapped = symbol_mapping.get(symbol)
                if mapped and mapped.get("market") == market_type:
                    symbols.append(mapped["symbol"])

        elif trending_source == "binance":
            response = requests.get(BINANCE_TRENDING_API, timeout=5)
            response.raise_for_status()
            data = response.json()
            articles = data.get("data", {}).get("articles", [])
            for article in articles:
                title = article.get("title", "")
                for key in symbol_mapping:
                    if key in title.lower():
                        mapped = symbol_mapping[key]
                        if mapped["market"] == market_type:
                            symbols.append(mapped["symbol"])

        elif trending_source == "lunarcrush" and LUNARCRUSH_API_KEY:
            url = f"{LUNARCRUSH_TRENDING_API}&key={LUNARCRUSH_API_KEY}"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            assets = data.get("data", [])
            for asset in assets:
                symbol = asset.get("symbol", "").lower()
                mapped = symbol_mapping.get(symbol)
                if mapped and mapped.get("market") == market_type:
                    symbols.append(mapped["symbol"])

        # סינון לפי נפח אם הוגדר
        if min_volume is not None and volume_lookup is not None:
            symbols = [s for s in symbols if volume_lookup.get(s, 0) >= min_volume]

        return symbols or ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

    except Exception:
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

def get_combined_trending_symbols(
    market_type: str = "futures",
    min_volume: Optional[float] = None,
    volume_lookup: Optional[Dict[str, float]] = None
) -> List[str]:
    """
    מאחד סמלים מטרנדינג מכל המקורות הנתמכים (coingecko + binance + lunarcrush)
    """
    sources = ["coingecko", "binance", "lunarcrush"]
    combined = []
    for source in sources:
        symbols = get_trending_symbols(
            trending_source=source,
            market_type=market_type,
            min_volume=min_volume,
            volume_lookup=volume_lookup
        )
        combined.extend(symbols)
    # החזרת רשימה ממוינת וייחודית
    return sorted(list(set(combined)))























































































































































































































































































































































































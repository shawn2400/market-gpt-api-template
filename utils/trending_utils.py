# utils/trending_utils.py

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

_cache: Dict[str, tuple[List[str], float]] = {}
CACHE_TTL = 600  # 10 דקות

def _cached(key: str) -> tuple[List[str], float]:
    return _cache.get(key, ([], 0))

def _store_cache(key: str, value: List[str]) -> None:
    _cache[key] = (value, time.time())

symbol_mapping: Dict[str, Dict[str, str]] = {
    # ... מיפוי מלא (קצר כאן בשביל הדוג') ...
    "btc": {"symbol": "BTCUSDT", "market": "futures"},
    "eth": {"symbol": "ETHUSDT", "market": "futures"},
    "bnb": {"symbol": "BNBUSDT", "market": "futures"},
    # ... המשך ...
}

DEFAULT_SOURCES = ["binance", "lunarcrush", "coingecko"]

def get_trending_symbols(trending_source: Optional[str] = None,
                         market_type: str = "spot",
                         min_volume: Optional[float] = None,
                         volume_lookup: Optional[Dict[str, float]] = None,
                         top: Optional[int] = None,
                         min_change_percent: Optional[float] = None) -> List[str]:

    if not trending_source:
        trending_source = DEFAULT_SOURCES[0]
    trending_source = trending_source.lower()
    base_market = "futures" if market_type == "grid" else market_type

    cache_key = f"{trending_source}:{base_market}:{min_volume}:{top}:{min_change_percent}"
    symbols, ts = _cached(cache_key)
    if symbols and (time.time() - ts < CACHE_TTL):
        logging.info(f"[trending] Using cache for {trending_source} ({len(symbols)} symbols)")
        return symbols

    logging.info(f"[trending] Fetching from {trending_source}...")
    symbols = []
    try:
        if trending_source == "binance":
            resp = requests.get(BINANCE_TRENDING_API, timeout=5)
            data = resp.json().get("data", {}).get("articles", [])
            for art in data:
                title = art.get("title", "").lower()
                for key, info in symbol_mapping.items():
                    if key in title and info.get("market") == base_market:
                        symbols.append(info["symbol"])

        elif trending_source == "lunarcrush":
            if not LUNARCRUSH_API_KEY:
                logging.warning("[trending] Missing LunarCrush API key.")
            else:
                url = f"{LUNARCRUSH_TRENDING_API}&key={LUNARCRUSH_API_KEY}"
                resp = requests.get(url, timeout=5)
                for asset in resp.json().get("data", []):
                    sym = asset.get("symbol", "").lower()
                    mapped = symbol_mapping.get(sym)
                    if mapped and mapped.get("market") == base_market:
                        symbols.append(mapped["symbol"])

        elif trending_source == "coingecko":
            resp = requests.get(COINGECKO_API, timeout=5)
            ids = [c['item']['id'] for c in resp.json().get("coins", [])]
            if ids:
                mr = requests.get(COINGECKO_MARKET_API,
                                  params={"vs_currency": "usd", "ids": ",".join(ids),
                                          "price_change_percentage": "24h"}, timeout=5)
                for coin in mr.json():
                    sym = coin.get("symbol", "").lower()
                    change = coin.get("price_change_percentage_24h", 0.0)
                    mapped = symbol_mapping.get(sym)
                    if mapped and mapped.get("market") == base_market:
                        if min_change_percent is None or change >= min_change_percent:
                            symbols.append(mapped["symbol"])

        if min_volume and volume_lookup:
            symbols = [s for s in symbols if volume_lookup.get(s, 0) >= min_volume]

        if top is not None and len(symbols) > top:
            symbols = symbols[:top]

        if not symbols:
            raise RuntimeError("No symbols found")

        _store_cache(cache_key, symbols)
        logging.info(f"[trending] {trending_source} returned {len(symbols)} symbols")
        return symbols

    except Exception as e:
        logging.error(f"[trending] Error fetching {trending_source}: {e}")

    fallback = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    _store_cache(cache_key, fallback)
    return fallback































































































































































































































































































































































































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
    "btc": {"symbol": "BTCUSDT", "market": "futures"},
    "eth": {"symbol": "ETHUSDT", "market": "futures"},
    "bnb": {"symbol": "BNBUSDT", "market": "futures"},
    "sol": {"symbol": "SOLUSDT", "market": "futures"},
    "xrp": {"symbol": "XRPUSDT", "market": "futures"},
    "ada": {"symbol": "ADAUSDT", "market": "futures"},
    "doge": {"symbol": "DOGEUSDT", "market": "futures"},
    "avax": {"symbol": "AVAXUSDT", "market": "futures"},
    "dot": {"symbol": "DOTUSDT", "market": "futures"},
    "link": {"symbol": "LINKUSDT", "market": "futures"},
    "matic": {"symbol": "MATICUSDT", "market": "futures"},
    "uni": {"symbol": "UNIUSDT", "market": "futures"},
    "ltc": {"symbol": "LTCUSDT", "market": "futures"},
    "shib": {"symbol": "SHIBUSDT", "market": "futures"},
    "near": {"symbol": "NEARUSDT", "market": "futures"},
    "fil": {"symbol": "FILUSDT", "market": "futures"},
    "atom": {"symbol": "ATOMUSDT", "market": "futures"},
    "egld": {"symbol": "EGLDUSDT", "market": "futures"},
    "ar": {"symbol": "ARUSDT", "market": "futures"},
    "blur": {"symbol": "BLURUSDT", "market": "futures"},
    "op": {"symbol": "OPUSDT", "market": "futures"},
    "sui": {"symbol": "SUIUSDT", "market": "futures"},
    "inj": {"symbol": "INJUSDT", "market": "futures"},
    "gala": {"symbol": "GALAUSDT", "market": "futures"},
    "rndr": {"symbol": "RNDRUSDT", "market": "futures"},
    "rdnt": {"symbol": "RDNTUSDT", "market": "futures"},
    "woo": {"symbol": "WOOUSDT", "market": "futures"},
    "enj": {"symbol": "ENJUSDT", "market": "futures"},
    "cake": {"symbol": "CAKEUSDT", "market": "futures"},
    "chz": {"symbol": "CHZUSDT", "market": "futures"},
    "alpha": {"symbol": "ALPHAUSDT", "market": "futures"},
    "band": {"symbol": "BANDUSDT", "market": "futures"},
    "mask": {"symbol": "MASKUSDT", "market": "futures"},
    "agix": {"symbol": "AGIXUSDT", "market": "futures"},
    "fet": {"symbol": "FETUSDT", "market": "futures"},
    "ocean": {"symbol": "OCEANUSDT", "market": "futures"},
    "rose": {"symbol": "ROSEUSDT", "market": "futures"},
    "sxp": {"symbol": "SXPUSDT", "market": "futures"},
    "flow": {"symbol": "FLOWUSDT", "market": "futures"},
    "ens": {"symbol": "ENSUSDT", "market": "futures"},
    "cfx": {"symbol": "CFXUSDT", "market": "futures"},
    "lina": {"symbol": "LINAUSDT", "market": "futures"},
    "trb": {"symbol": "TRBUSDT", "market": "futures"},
    "ach": {"symbol": "ACHUSDT", "market": "futures"},
    "magic": {"symbol": "MAGICUSDT", "market": "futures"},
    "1000sats": {"symbol": "1000SATSUSDT", "market": "futures"},
    "ena": {"symbol": "ENAUSDT", "market": "futures"},
    "jup": {"symbol": "JUPUSDT", "market": "futures"},
    "beam": {"symbol": "BEAMXUSDT", "market": "futures"},
    "not": {"symbol": "NOTUSDT", "market": "futures"}
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

def get_combined_trending_symbols(market_type: str = "futures",
                                   min_volume: Optional[float] = None,
                                   volume_lookup: Optional[Dict[str, float]] = None,
                                   sources: List[str] = None,
                                   top: Optional[int] = None,
                                   min_change_percent: Optional[float] = None) -> List[str]:

    if sources is None:
        sources = DEFAULT_SOURCES

    combined = []
    for src in sources:
        syms = get_trending_symbols(
            trending_source=src,
            market_type=market_type,
            min_volume=min_volume,
            volume_lookup=volume_lookup,
            top=top,
            min_change_percent=min_change_percent
        )
        combined.extend(syms)

    return sorted(set(combined))






























































































































































































































































































































































































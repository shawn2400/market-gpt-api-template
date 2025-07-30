# ===== קובץ: scanner_utils.py =====

import asyncio
import logging
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.binance_client import client
from utils.quality_score import compute_quality_score
from utils.ai_analysis import predict_optimal_sl_tp
from utils.trending_utils import get_trending_symbols
import os

semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_SCANS", 15)))

def get_symbols(market_type="futures", min_volume=1_000_000, trending_only=False):
    """
    מחזיר רשימת סמלים פעילים (TRADING) מ-Binance לפי סוג שוק, נפח, Trending.
    """
    try:
        if market_type == "futures":
            info = client.futures_exchange_info()
        elif market_type == "spot":
            info = client.get_exchange_info()
        else:
            raise ValueError("market_type must be 'futures' or 'spot'")
        all_symbols = [
            x['symbol'] for x in info['symbols']
            if x['quoteAsset'] == 'USDT' and x['status'] == 'TRADING'
        ]
        # Trending Only
        if trending_only:
            trending = set(get_trending_symbols())
            symbols = [s for s in all_symbols if s in trending]
        else:
            symbols = all_symbols
        # Volume filter
        filtered = []
        for s in symbols:
            try:
                ticker = client.futures_ticker(symbol=s) if market_type == "futures" else client.get_ticker(symbol=s)
                vol = float(ticker.get('quoteVolume', 0))
                if vol >= min_volume:
                    filtered.append(s)
            except Exception:
                continue
        return filtered
    except Exception as e:
        logging.error(f"[!] שגיאה בשליפת סמלים ({market_type}): {e}")
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]

# שאר הפונקציות (safe_get_klines, analyze_symbol, scan_all) נשארות כמו אצלך — רק תעביר לפרמטרים min_volume, trending_only הלאה.






















































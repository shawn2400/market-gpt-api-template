# ===== קובץ: scanner_utils.py =====

import asyncio
import logging
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.binance_client import client
from utils.quality_score import compute_quality_score
from utils.ai_analysis import predict_optimal_sl_tp

semaphore = asyncio.Semaphore(10)

def get_symbols(market_type="futures", min_volume=1_000_000):
    """
    מחזיר רשימת סמלים פעילים לפי סוג שוק ונפח מינימלי (USDT).
    """
    try:
        if market_type == "futures":
            info = client.futures_exchange_info()
        elif market_type == "spot":
            info = client.get_exchange_info()
        else:
            raise ValueError("market_type must be 'futures' or 'spot'")
        symbols = [
            x['symbol'] for x in info['symbols']
            if x['quoteAsset'] == 'USDT' and x['status'] == 'TRADING'
        ]
        # סינון לפי volume
        filtered = []
        for s in symbols:
            try:
                if market_type == "futures":
                    ticker = client.futures_ticker(symbol=s)
                else:
                    ticker = client.get_ticker(symbol=s)
                vol = float(ticker.get('quoteVolume', 0))
                if vol >= min_volume:
                    filtered.append(s)
            except Exception as e:
                continue
        return filtered
    except Exception as e:
        logging.error(f"[!] שגיאה בשליפת סמלים ({market_type}): {e}")
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]

# כל שאר הפונקציות (safe_get_klines, analyze_symbol, scan_all וכו') — כמו אצלך, אפשר להשאיר.

# דוגמה לקריאה:
# symbols = get_symbols(market_type="futures", min_volume=1_000_000)





















































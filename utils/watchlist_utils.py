# utils/watchlist_utils.py

import json
import os
from typing import List, Dict
from utils.trending_utils import get_trending_symbols
from utils.multi_tf_scanner import analyze_symbol

WATCHLIST_FILE = "watchlist.json"

def load_watchlist() -> List[Dict]:
    """ טוען את רשימת המעקב מהדיסק """
    if not os.path.exists(WATCHLIST_FILE):
        return []
    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_watchlist(watchlist: List[Dict]) -> None:
    """ שומר את רשימת המעקב לקובץ """
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(watchlist, f, ensure_ascii=False, indent=2)

def generate_trending_watchlist(top: int = 30, min_quality: int = 6, market: str = "futures") -> None:
    """
    בונה אוטומטית רשימת מעקב לפי trending + ניתוח איכות.
    סף איכות ברירת מחדל: 6
    """
    symbols = get_trending_symbols(top=top, market_type=market)
    watchlist = []

    for symbol in symbols:
        try:
            result = analyze_symbol(symbol, market=market, interval1="15m", interval2="1h")
            quality = result.get("quality_score")
            direction = result.get("direction")
            if quality is not None and quality >= min_quality and direction:
                watchlist.append({
                    "symbol": symbol,
                    "direction": direction,
                    "quality_score": quality
                })
        except Exception as e:
            print(f"[Watchlist] ⚠️ שגיאה בניתוח {symbol}: {e}")

    save_watchlist(watchlist)
    print(f"[Watchlist] ✅ נשמרו {len(watchlist)} סמלים לקובץ watchlist.json")








# ===== קובץ: utils/watchlist_utils.py =====

import json
import os
from datetime import datetime

WATCHLIST_FILE = "watchlist.json"

def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        return []
    with open(WATCHLIST_FILE, "r") as f:
        return json.load(f)

def save_watchlist(watchlist):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(watchlist, f, indent=2)

def add_to_watchlist(symbol, direction, quality_score, reason=None):
    wl = load_watchlist()
    item = {
        "symbol": symbol,
        "direction": direction,
        "quality_score": quality_score,
        "reason": reason or "",
        "timestamp": datetime.utcnow().isoformat()
    }
    if not any(x["symbol"] == symbol and x["direction"] == direction for x in wl):
        wl.append(item)
        save_watchlist(wl)
        print(f"[WATCHLIST] הוסף: {symbol} {direction}")
        return True
    return False

def auto_update_watchlist(trades, threshold=7):
    for t in trades:
        if t.get("quality_score", 0) >= threshold:
            add_to_watchlist(
                t["symbol"],
                t["direction"],
                t.get("quality_score", 0),
                reason=f"עבר QS {threshold}+ Multi-TF"
            )

def get_default_watchlist(market_type="futures"):
    """
    מחזיר רשימת ברירת מחדל של סמלים למקרה שאין טרנדינג זמין.
    """
    if market_type == "spot":
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
    elif market_type == "grid":
        return ["BCHUSDT", "TRXUSDT", "LINKUSDT", "MATICUSDT", "LTCUSDT"]
    return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "OPUSDT", "AVAXUSDT", "NEARUSDT"]




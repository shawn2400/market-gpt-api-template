# utils/trade_storage.py

import json
import os
from typing import Dict, List

# נתיב לקובץ הטריידים הפתוחים (ניתן לשנות דרך ENV)
TRADES_FILE = os.getenv("TRADES_FILE", "open_trades.json")

def load_open_trades() -> List[Dict]:
    """ טוען את רשימת הטריידים הפתוחים מהדיסק """
    if not os.path.exists(TRADES_FILE):
        return []
    with open(TRADES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def get_open_trades_count() -> int:
    """ מחזיר את מספר הטריידים הפתוחים כרגע """
    return len(load_open_trades())

def save_trade(trade: Dict) -> None:
    """ שומר טרייד חדש לתוך הרשימה בקובץ JSON """
    trades = load_open_trades()
    trades.append(trade)
    with open(TRADES_FILE, "w", encoding="utf-8") as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)


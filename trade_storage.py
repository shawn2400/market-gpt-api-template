# utils/trade_storage.py

import json
import os

TRADE_FILE = "saved_trades.json"

def load_trades():
    if not os.path.exists(TRADE_FILE):
        return []
    try:
        with open(TRADE_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] שגיאה בקריאת טריידים: {e}")
        return []

def save_trade(trade):
    trades = load_trades()
    trades.append(trade)
    try:
        with open(TRADE_FILE, "w") as f:
            json.dump(trades, f, indent=2)
        return True
    except Exception as e:
        print(f"[!] שגיאה בשמירת טרייד: {e}")
        return False

def clear_trades():
    try:
        with open(TRADE_FILE, "w") as f:
            json.dump([], f)
        return True
    except Exception as e:
        print(f"[!] שגיאה באיפוס טריידים: {e}")
        return False


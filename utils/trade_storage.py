# utils/trade_storage.py
import json
import os
from typing import Dict, List

TRADES_FILE = os.getenv("TRADES_FILE", "open_trades.json")

def load_open_trades() -> List[Dict]:
    if not os.path.exists(TRADES_FILE):
        return []
    with open(TRADES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def get_open_trades_count() -> int:
    return len(load_open_trades())

def save_trade(trade: Dict) -> None:
    trades = load_open_trades()
    trades.append(trade)
    with open(TRADES_FILE, "w", encoding="utf-8") as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)



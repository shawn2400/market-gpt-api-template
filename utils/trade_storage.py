# utils/trade_storage.py

import json
import os

TRADES_FILE = "open_trades.json"

def load_open_trades():
    if not os.path.exists(TRADES_FILE):
        return []
    with open(TRADES_FILE, "r") as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_open_trades(trades):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)

def add_trade(trade):
    trades = load_open_trades()
    trades.append(trade)
    save_open_trades(trades)

def find_trade(symbol, direction):
    trades = load_open_trades()
    for t in trades:
        if t["symbol"].upper() == symbol.upper() and t["direction"].upper() == direction.upper():
            return t
    return None

def update_trade(trade):
    trades = load_open_trades()
    for i, t in enumerate(trades):
        if t["symbol"].upper() == trade["symbol"].upper() and t["direction"].upper() == trade["direction"].upper():
            trades[i] = trade
            save_open_trades(trades)
            return True
    return False













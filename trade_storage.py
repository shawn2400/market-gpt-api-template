# utils/trade_storage.py

import json
from datetime import datetime

TRADES_FILE = "pnl_tracker.json"

def save_trade(data):
    try:
        trade_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": data["symbol"],
            "entry": data["entry"],
            "stop": data["stop"],
            "tp": data["tp"],
            "direction": data["direction"],
            "leverage": data["leverage"],
            "confidence": data.get("confidence", 90),
            "quality_score": data.get("quality_score", 5),
            "type": data.get("type", "REGULAR")
        }

        try:
            with open(TRADES_FILE, "r") as f:
                trades = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            trades = []

        trades.append(trade_data)

        with open(TRADES_FILE, "w") as f:
            json.dump(trades, f, indent=2)

        print(f"✅ טרייד נשמר: {trade_data['symbol']} | {trade_data['direction']} @ {trade_data['entry']}")
        return True
    except Exception as e:
        print(f"[!] שגיאה בשמירת טרייד: {e}")
        return False

def load_trades():
    try:
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def delete_trade(symbol):
    try:
        trades = load_trades()
        updated_trades = [t for t in trades if t["symbol"] != symbol]

        with open(TRADES_FILE, "w") as f:
            json.dump(updated_trades, f, indent=2)

        print(f"🗑️ טרייד נמחק: {symbol}")
        return True
    except Exception as e:
        print(f"[!] שגיאה במחיקת טרייד: {e}")
        return False




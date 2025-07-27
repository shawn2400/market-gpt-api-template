# utils/trade_storage.py

import json
from datetime import datetime

TRADES_FILE = "pnl_tracker.json"

def save_trade(symbol, entry, stop, tp, direction, leverage, confidence, quality_score, trade_type="REGULAR"):
    try:
        trade_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "entry": entry,
            "stop": stop,
            "tp": tp,
            "direction": direction,
            "leverage": leverage,
            "confidence": confidence,
            "quality_score": quality_score,
            "type": trade_type
        }

        try:
            with open(TRADES_FILE, "r") as f:
                trades = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            trades = []

        trades.append(trade_data)

        with open(TRADES_FILE, "w") as f:
            json.dump(trades, f, indent=2)

        print(f"✅ טרייד נשמר: {symbol} | {direction} | {entry}")
        return True

    except Exception as e:
        print(f"[!] שגיאה בשמירת טרייד: {e}")
        return False



# utils/trade_storage.py

import json
import os
from datetime import datetime

TRADES_FILE = "trades_log.json"

def save_trade(trade_data):
    """
    שומר טרייד לקובץ JSON.
    מוסיף תאריך וזמן אוטומטיים אם חסרים.
    """
    try:
        if not os.path.exists(TRADES_FILE):
            data = []
        else:
            with open(TRADES_FILE, "r") as f:
                data = json.load(f)

        trade_data.setdefault("timestamp", datetime.utcnow().isoformat())
        trade_data.setdefault("user_id", "default")

        data.append(trade_data)

        with open(TRADES_FILE, "w") as f:
            json.dump(data, f, indent=4)

        return True

    except Exception as e:
        print(f"[!] שגיאה בשמירת טרייד: {e}")
        return False






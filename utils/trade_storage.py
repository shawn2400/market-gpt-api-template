# utils/trade_storage.py

import json
import os
from datetime import datetime

TRADES_FILE = "trades_log.json"

def save_trade(trade_data):
    """
    שומר טרייד לקובץ JSON. מוסיף תאריך וזמן אם חסרים.
    יוצר את הקובץ אם לא קיים. מחזיר True אם הצליח.
    """
    try:
        # טעינת טריידים קיימים או התחלה מחדש
        data = []
        if os.path.exists(TRADES_FILE):
            with open(TRADES_FILE, "r") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    print("[!] קובץ קיים אך פגום – התחלה מחדש.")
                    data = []

        # ודא שכל המפתחות הקריטיים קיימים
        trade_data.setdefault("timestamp", datetime.utcnow().isoformat())
        trade_data.setdefault("user_id", "default")
        trade_data.setdefault("symbol", "")
        trade_data.setdefault("entry", 0)
        trade_data.setdefault("stop", 0)
        trade_data.setdefault("tp", 0)
        trade_data.setdefault("direction", "LONG")
        trade_data.setdefault("leverage", 1)
        trade_data.setdefault("confidence", 0)
        trade_data.setdefault("quality_score", 0)
        trade_data.setdefault("type", "REGULAR")

        data.append(trade_data)

        with open(TRADES_FILE, "w") as f:
            json.dump(data, f, indent=4)

        return True

    except Exception as e:
        print(f"[!] שגיאה בשמירת טרייד: {e}")
        return False


def load_trades():
    """
    טוען את רשימת הטריידים הקיימים מהקובץ.
    מחזיר רשימה ריקה אם לא קיים או תקול.
    """
    if not os.path.exists(TRADES_FILE):
        return []

    try:
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] שגיאה בטעינת טריידים: {e}")
        return []







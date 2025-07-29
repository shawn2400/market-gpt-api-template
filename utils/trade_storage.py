import json
import os
import uuid
from datetime import datetime

TRADES_FILE = "trades_log.json"


def save_trade(trade_data: dict) -> bool:
    """
    שמירת טרייד בודד לקובץ JSON.
    מוסיף שדות חסרים כמו זיהוי ייחודי ותאריך.
    """
    try:
        # טען נתונים קיימים
        data = []
        if os.path.exists(TRADES_FILE):
            with open(TRADES_FILE, "r") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    print("⚠️ קובץ קיים אך פגום – מתחיל חדש")
                    data = []

        # הגדרות ברירת מחדל
        trade_data.setdefault("id", str(uuid.uuid4()))
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
        trade_data.setdefault("type", "REGULAR")  # יכול להיות גם "GRID"
        trade_data.setdefault("budget", 0)
        trade_data.setdefault("quantity", 0)
        trade_data.setdefault("status", "OPEN")  # OPEN / CLOSED / CANCELLED

        data.append(trade_data)

        with open(TRADES_FILE, "w") as f:
            json.dump(data, f, indent=4)

        print(f"✅ טרייד נשמר: {trade_data['symbol']} @ {trade_data['entry']}")
        return True

    except Exception as e:
        print(f"[!] שגיאה בשמירת טרייד: {e}")
        return False


def load_trades() -> list:
    """
    טוען את כל הטריידים מהקובץ.
    """
    try:
        if not os.path.exists(TRADES_FILE):
            return []
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] שגיאה בטעינת טריידים: {e}")
        return []


def get_open_trades() -> list:
    """
    מחזיר רק טריידים פתוחים.
    """
    return [t for t in load_trades() if t.get("status") == "OPEN"]


def get_last_trade(symbol: str = None) -> dict:
    """
    מחזיר את הטרייד האחרון לפי הסימול (אם סופק).
    """
    trades = load_trades()
    if symbol:
        trades = [t for t in trades if t.get("symbol") == symbol]
    if not trades:
        return {}
    return trades[-1]










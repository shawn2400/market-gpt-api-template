# utils/trade_storage.py

import json
import os
import uuid
from datetime import datetime
from typing import List, Dict

TRADES_FILE = "trades_log.json"

def _load_data() -> List[Dict]:
    """טוען את כל הטריידים מהקובץ (או מחזיר ריק)."""
    if not os.path.exists(TRADES_FILE):
        return []
    try:
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception) as e:
        print(f"[!] שגיאה בטעינת קובץ טריידים: {e}")
        return []

def _save_data(data: List[Dict]) -> bool:
    """שומר את כל המידע לקובץ."""
    try:
        with open(TRADES_FILE, "w") as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        print(f"[!] שגיאה בשמירה: {e}")
        return False

def save_trade(trade_data: Dict) -> bool:
    """
    שמירת טרייד בודד לקובץ JSON. מוסיף מזהה ותאריך אם חסרים.
    """
    try:
        data = _load_data()

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
        trade_data.setdefault("type", "REGULAR")  # REGULAR / GRID
        trade_data.setdefault("budget", 0)
        trade_data.setdefault("quantity", 0)
        trade_data.setdefault("status", "OPEN")  # OPEN / CLOSED / CANCELLED

        data.append(trade_data)
        success = _save_data(data)

        if success:
            print(f"✅ טרייד נשמר: {trade_data['symbol']} @ {trade_data['entry']}")
        return success
    except Exception as e:
        print(f"[!] שגיאה בשמירת טרייד: {e}")
        return False

def load_trades() -> List[Dict]:
    """טוען את כל הטריידים מהקובץ."""
    return _load_data()

def get_open_trades() -> List[Dict]:
    """מחזיר רק טריידים שעדיין פתוחים."""
    return [t for t in _load_data() if t.get("status") == "OPEN"]

def get_last_trade(symbol: str = None) -> Dict:
    """מחזיר את הטרייד האחרון לפי הסימול (אם סופק)."""
    trades = _load_data()
    if symbol:
        trades = [t for t in trades if t.get("symbol") == symbol.upper()]
    return trades[-1] if trades else {}











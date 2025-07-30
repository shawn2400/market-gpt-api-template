# ===== קובץ: utils/trade_storage.py =====

import json
import os
import uuid
from datetime import datetime
from typing import List, Dict

TRADES_FILE = "trades_log.json"
SCANNED_FILE = "scanned_trades.json"

def _load_data(file=TRADES_FILE) -> List[Dict]:
    if not os.path.exists(file):
        return []
    try:
        with open(file, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] שגיאה בטעינת קובץ {file}: {e}")
        return []

def _save_data(data: List[Dict], file=TRADES_FILE) -> bool:
    try:
        with open(file, "w") as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        print(f"[!] שגיאה בשמירה: {e}")
        return False

def save_trade(trade_data: Dict) -> bool:
    try:
        data = _load_data()
        trade_data.setdefault("id", str(uuid.uuid4()))
        trade_data.setdefault("timestamp", datetime.utcnow().isoformat())
        trade_data.setdefault("status", "OPEN")
        data.append(trade_data)
        return _save_data(data)
    except Exception as e:
        print(f"[!] שגיאה בשמירת טרייד: {e}")
        return False

def get_open_trades() -> List[Dict]:
    return [t for t in _load_data() if t.get("status", "OPEN") == "OPEN"]

def save_scanned_trade(trade_data: Dict):
    data = _load_data(SCANNED_FILE)
    trade_data.setdefault("scanned_at", datetime.utcnow().isoformat())
    data.append(trade_data)
    _save_data(data, SCANNED_FILE)

def load_scanned_trades():
    return _load_data(SCANNED_FILE)













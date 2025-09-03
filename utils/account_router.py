# utils/account_router.py
import os
import json
import threading
from typing import Optional, List, Dict

ACCOUNTS_FILE = os.getenv("ACCOUNTS_CONFIG_PATH", "accounts/accounts_config.json")

_accounts_cache: List[Dict] = []
_accounts_lock = threading.Lock()
_last_mtime: float = 0.0


def _load_accounts(force: bool = False) -> List[Dict]:
    """טוען חשבונות מהקובץ עם caching כדי להימנע מקריאות דיסק תכופות"""
    global _accounts_cache, _last_mtime
    try:
        mtime = os.path.getmtime(ACCOUNTS_FILE)
        if force or (mtime != _last_mtime) or not _accounts_cache:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    _accounts_cache = data
                    _last_mtime = mtime
    except Exception:
        return []
    return _accounts_cache


def get_account_credentials(account_id: str) -> Optional[Dict]:
    """מחזיר מפתחות API לחשבון לפי מזהה (id)"""
    for acc in _load_accounts():
        if acc.get("id") == account_id:
            return {
                "api_key": acc.get("api_key"),
                "api_secret": acc.get("api_secret"),
                "market": acc.get("market", "futures"),
            }
    return None


def list_account_ids() -> List[str]:
    """רשימת כל חשבונות שהוגדרו"""
    return [a.get("id") for a in _load_accounts() if a.get("id")]




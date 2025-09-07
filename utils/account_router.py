# utils/account_router.py
import os, json, threading, logging
from typing import Optional, List, Dict

logger = logging.getLogger("algogpt.account_router")

ACCOUNTS_FILE = os.getenv("ACCOUNTS_CONFIG_PATH", "accounts/accounts_config.json")

_accounts_cache: List[Dict] = []
_accounts_lock = threading.Lock()
_last_mtime: float = 0.0

def _load_accounts(force: bool = False) -> List[Dict]:
    """
    טוען חשבונות מהקובץ עם caching כדי להימנע מקריאות דיסק מיותרות.
    אם הקובץ השתנה → נטען מחדש.
    """
    global _accounts_cache, _last_mtime
    try:
        if not os.path.exists(ACCOUNTS_FILE):
            logger.warning(f"⚠️ accounts_config.json not found at {ACCOUNTS_FILE}")
            return []

        mtime = os.path.getmtime(ACCOUNTS_FILE)
        with _accounts_lock:
            if force or (mtime != _last_mtime) or not _accounts_cache:
                with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    _accounts_cache = data
                    _last_mtime = mtime
                    logger.info(f"🔄 Loaded {len(_accounts_cache)} accounts from {ACCOUNTS_FILE}")
    except Exception as e:
        logger.error(f"Failed to load accounts: {e}")
        return []
    return _accounts_cache

def get_account_credentials(account_id: str) -> Optional[Dict]:
    """
    מחזיר מפתחות API לחשבון לפי מזהה account_id.
    מחזיר None אם לא נמצא או אם אין מפתחות.
    """
    for acc in _load_accounts():
        if str(acc.get("id")) == str(account_id):
            return {
                "api_key": acc.get("api_key"),
                "api_secret": acc.get("api_secret"),
                "market": acc.get("market", "futures"),
            }
    logger.warning(f"⚠️ Account {account_id} not found in config")
    return None

def list_account_ids() -> List[str]:
    """מחזיר רשימה של כל account_id שהוגדרו בקובץ."""
    return [str(a.get("id")) for a in _load_accounts() if a.get("id")]





# utils/account_router.py
import os
from typing import Optional
import json

ACCOUNTS_FILE = os.getenv("ACCOUNTS_CONFIG_PATH", "accounts/accounts_config.json")

def _load_accounts() -> list[dict]:
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def get_account_credentials(account_id: str) -> Optional[dict]:
    for acc in _load_accounts():
        if acc.get("id") == account_id:
            return {
                "api_key": acc.get("api_key"),
                "api_secret": acc.get("api_secret"),
                "market": acc.get("market", "futures"),
            }
    return None

def list_account_ids() -> list[str]:
    return [a.get("id") for a in _load_accounts() if a.get("id")]




# utils/account_router.py
from __future__ import annotations
import os, json
from typing import Dict, Any
from fastapi import APIRouter, Depends
from utils.auth import require_api_key

router = APIRouter(
    prefix="/accounts",
    tags=["Accounts"],
    dependencies=[Depends(require_api_key)]
)

ACCOUNTS_PATH = os.getenv("ACCOUNTS_CONFIG_PATH", "accounts/accounts_config.json")

@router.get("/list")
def list_accounts() -> Dict[str, Any]:
    try:
        with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"ok": True, "accounts": data or {}}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.get("/active")
def get_active_account() -> Dict[str, Any]:
    return {"ok": True, "active": os.getenv("BINANCE_API_KEY", "default")}



# utils/account_router.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any
import os, json

router = APIRouter(prefix="/accounts", tags=["Accounts"])

ACCOUNTS_FILE = os.getenv("ACCOUNTS_CONFIG_FILE", "accounts/accounts_config.json")

def _load_accounts() -> List[Dict[str, Any]]:
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("accounts") or []
    except Exception as e:
        print(f"[account_router] Failed to load accounts: {e}")
        return []

@router.get("/list")
def list_accounts() -> Dict[str, Any]:
    accounts = _load_accounts()
    return {"ok": True, "total": len(accounts), "items": accounts}

@router.get("/active")
def active_account() -> Dict[str, Any]:
    accounts = _load_accounts()
    actives = [a for a in accounts if a.get("active")]
    if not actives:
        raise HTTPException(status_code=404, detail="No active account configured")
    return {"ok": True, "account": actives[0]}

@router.get("/by-name")
def account_by_name(name: str = Query(..., min_length=2, max_length=32)) -> Dict[str, Any]:
    accounts = _load_accounts()
    for a in accounts:
        if a.get("name", "").lower() == name.strip().lower():
            return {"ok": True, "account": a}
    raise HTTPException(status_code=404, detail=f"Account not found: {name}")


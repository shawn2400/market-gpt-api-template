# routes/health_full.py
from __future__ import annotations
import os, json, asyncio
from typing import Dict, Any, List
from fastapi import APIRouter
from utils import config
from utils.binance_client import ping_and_info, get_client
from utils.ai_client import ai_healthcheck

router = APIRouter(tags=["Config"])

REQUIRED_ENV = [
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "OPENAI_API_KEY",
    "CRYPTO_PANIC_API_KEY",
    "ALERT_EMAIL_ADDRESS",
    "ALERT_EMAIL_PASSWORD",
]
CRITICAL_FILES = ["watchlist.json", "open_trades.json", "pnl_tracker.json"]

def _env_status() -> Dict[str, Any]:
    missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
    return {"ok": len(missing) == 0, "missing": missing}

def _files_status() -> Dict[str, Any]:
    details: List[Dict[str, Any]] = []
    ok = True
    for f in CRITICAL_FILES:
        exists = os.path.exists(f)
        size = os.path.getsize(f) if exists else 0
        readable = False
        if exists:
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    json.load(fh)
                readable = True
            except Exception:
                ok = False
        else:
            ok = False
        details.append({"file": f, "exists": exists, "readable_json": readable, "size": size})
    return {"ok": ok, "details": details}

@router.get("/health/full", summary="Full system health (Binance/AI/ENV/files)")
async def health_full() -> Dict[str, Any]:
    # Binance public ping
    try:
        binance_ping = bool(ping_and_info())
    except Exception:
        binance_ping = False

    # Binance private (optional)
    binance_private = None
    if getattr(config, "BINANCE_API_KEY", "") and getattr(config, "BINANCE_API_SECRET", ""):
        try:
            client = get_client()
            await asyncio.to_thread(client.futures_account_balance)
            binance_private = True
        except Exception:
            binance_private = False

    # AI health
    try:
        ai = await ai_healthcheck()
    except Exception as e:
        ai = {"ok": False, "error": str(e)}

    envs = _env_status()
    files = _files_status()
    ok = binance_ping and (ai.get("ok") is True) and files["ok"]

    return {
        "ok": ok,
        "binance": {"ping_ok": binance_ping, "private_ok": binance_private},
        "ai": ai,
        "env": envs,
        "files": files,
        "version": getattr(config, "OPENAI_MODEL", None),
    }

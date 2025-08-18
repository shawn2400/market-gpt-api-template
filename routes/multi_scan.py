# routes/multi_scan.py
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict
from fastapi import APIRouter

router = APIRouter(prefix="/scan", tags=["Scan"])

@router.get("/info", operation_id="getScanInfo")
async def get_scan_info() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": True,
        "now_utc": datetime.now(timezone.utc).isoformat(),
        "executor_running": False,
        "config": {},
        "notes": [],
    }
    # config
    try:
        from utils import config as cfg
        out["config"] = {
            "AUTO_RUN": bool(getattr(cfg, "AUTO_RUN", False)),
            "ENABLE_AUTO_TRADING": bool(getattr(cfg, "ENABLE_AUTO_TRADING", False)),
            "EXECUTE_TRADES": bool(getattr(cfg, "EXECUTE_TRADES", False)),
            "SCAN_INTERVAL": int(getattr(cfg, "SCAN_INTERVAL", 60)),
            "MIN_QUALITY_SCORE": float(getattr(cfg, "MIN_QUALITY_SCORE", 6)),
            "MAX_TRADE_BUDGET": float(getattr(cfg, "MAX_TRADE_BUDGET", 100.0)),
            "TRENDING_ONLY": bool(getattr(cfg, "TRENDING_ONLY", False)),
            "DEFAULT_INTERVAL": str(getattr(cfg, "DEFAULT_INTERVAL", "15m")),
            "SYMBOL_COOLDOWN_SEC": int(getattr(cfg, "SYMBOL_COOLDOWN_SEC", 600)),
            "MAX_TRADES_PER_TICK": int(getattr(cfg, "MAX_TRADES_PER_TICK", 3)),
        }
    except Exception:
        out["notes"].append("config_unavailable")

    # auto executor
    try:
        from utils.auto_executor import is_executor_running  # type: ignore
        out["executor_running"] = bool(is_executor_running())
    except Exception:
        out["notes"].append("auto_executor_unavailable")

    # binance client presence
    try:
        from utils.binance_client import futures_mark_price  # type: ignore
        _ = futures_mark_price  # just to ensure import works
        out["notes"].append("binance_client_ok")
    except Exception as e:
        out["notes"].append(f"binance_client_missing: {e!s}")

    return out























































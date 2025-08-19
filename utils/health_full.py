# utils/health_full.py
from __future__ import annotations

import os
import json
import asyncio
import time
from typing import Dict, Any, List, Optional

# FastAPI אופציונלי (מאפשר גם שימוש כראוטר ישירות אם תרצה לכלול את הקובץ כראוטר)
try:
    from fastapi import APIRouter
    _FASTAPI_AVAILABLE = True
except Exception:
    _FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore

# ---- תלויות פנימיות ----
try:
    from utils import config as _cfg  # type: ignore
except Exception:
    class _CfgFallback:
        AUTO_RUN = False
        OPENAI_MODEL = os.getenv("OPENAI_MODEL", "")
    _cfg = _CfgFallback()  # type: ignore

from utils.binance_client import ping_and_info, get_client, futures_mark_price
from utils.ai_client import ai_healthcheck

# --------------------------------------------------------------------------------------
# תצורה
# --------------------------------------------------------------------------------------

REQUIRED_ENV: List[str] = [
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "OPENAI_API_KEY",
    # אופציונלי אך אם נדרש אצלך במערכת – נשאיר בבדיקה
    "CRYPTO_PANIC_API_KEY",
    # אם קיימים אצלך – ידווח כחסר אם לא הוגדרו
    "ALERT_EMAIL_ADDRESS",
    "ALERT_EMAIL_PASSWORD",
]

CRITICAL_FILES: List[str] = [
    "watchlist.json",
    "open_trades.json",
    "pnl_tracker.json",
    # קבצים שברוב הפרויקטים אצלך קיימים – לא חובה, רק דו"ח
    "grid_tracker.json",
]

# מדגם לבדיקה ציבורית של מחיר (אפשר לשנות)
_HEALTH_SYMBOL = os.getenv("HEALTH_SYMBOL", "BTCUSDT")


# --------------------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------------------

def _env_status() -> Dict[str, Any]:
    missing: List[str] = []
    details: Dict[str, Optional[str]] = {}
    for k in REQUIRED_ENV:
        v = os.getenv(k)
        if not v:
            missing.append(k)
            details[k] = None
        else:
            # לא נחזיר ערכים אמיתיים (אבטחה), רק אורך וטשטוש
            details[k] = f"*** (len={len(v)})"
    return {
        "ok": len(missing) == 0,
        "missing": missing,
        "details": details,
    }


def _files_status() -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    ok = True
    for path in CRITICAL_FILES:
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        readable = False
        if exists:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    json.load(fh)
                readable = True
            except Exception:
                readable = False
                ok = False
        else:
            ok = False
        items.append({
            "file": path,
            "exists": exists,
            "size": size,
            "readable_json": readable,
        })
    return {"ok": ok, "details": items}


async def _binance_private_check() -> Dict[str, Any]:
    """
    בדיקה קלה שדורשת הרשאות – רצה ב-thread כדי לא לחסום event loop.
    """
    has_keys = bool(os.getenv("BINANCE_API_KEY")) and bool(os.getenv("BINANCE_API_SECRET"))
    if not has_keys:
        return {"ok": None, "reason": "missing_api_keys"}
    t0 = time.perf_counter()
    try:
        client = get_client()
        # קריאה פשוטה: מאזנת UM Futures (לא מעדכנת מצב, רק קוראת)
        bal = await asyncio.to_thread(client.futures_account_balance)
        dt = (time.perf_counter() - t0) * 1000.0
        return {"ok": True, "latency_ms": round(dt, 1), "sample_len": len(bal) if bal else 0}
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000.0
        return {"ok": False, "latency_ms": round(dt, 1), "error": str(e)}


async def _binance_public_check() -> Dict[str, Any]:
    """
    בדיקת חיבור ציבורי:
    - ping+exchangeInfo דרך ping_and_info (עם רוטציית דומיינים)
    - דגימת Mark Price לסימבול ברירת מחדל
    """
    meta = ping_and_info()  # לא async
    mark = futures_mark_price(_HEALTH_SYMBOL)  # לא async

    pub_ok = bool(meta.get("ping_ok")) and bool(meta.get("info_ok"))
    mark_ok = bool(mark.get("ok"))
    return {
        "ok": pub_ok and mark_ok,
        "ping_and_info": meta,
        "mark_price": {
            "symbol": _HEALTH_SYMBOL,
            "ok": mark_ok,
            "markPrice": mark.get("markPrice"),
            "endpoint": mark.get("endpoint"),
            "error": mark.get("error"),
        },
    }


# --------------------------------------------------------------------------------------
# API / Health aggregator
# --------------------------------------------------------------------------------------

async def health_full_status() -> Dict[str, Any]:
    """
    אוסף סטטוס מלא: Binance (public/private), AI, ENV, קבצים, גרסת מודל.
    לא מרים חריגות; תמיד מחזיר מבנה עקבי.
    """
    # Binance public
    try:
        binance_pub = await _binance_public_check()
    except Exception as e:
        binance_pub = {"ok": False, "error": f"public_check_failed: {e}"}

    # Binance private (אם יש מפתחות)
    try:
        binance_priv = await _binance_private_check()
    except Exception as e:
        binance_priv = {"ok": False, "error": f"private_check_failed: {e}"}

    # AI health
    try:
        ai = await ai_healthcheck()
        if not isinstance(ai, dict):
            ai = {"ok": False, "error": "invalid_ai_health_format"}
    except Exception as e:
        ai = {"ok": False, "error": str(e)}

    envs = _env_status()
    files = _files_status()

    ok = bool(binance_pub.get("ok")) and (ai.get("ok") is True) and files.get("ok", False)
    return {
        "ok": ok,
        "binance": {
            "public": binance_pub,
            "private": binance_priv,
        },
        "ai": ai,
        "env": envs,
        "files": files,
        "version": getattr(_cfg, "OPENAI_MODEL", "") or os.getenv("OPENAI_MODEL", ""),
    }


# --------------------------------------------------------------------------------------
# FastAPI Router (אופציונלי)
# אם תרצה לכלול ישירות את הקובץ הזה כראוטר:
# במיין: app.include_router(utils.health_full.router)
# או בקובץ routes/health.py: from utils.health_full import router
# --------------------------------------------------------------------------------------

if _FASTAPI_AVAILABLE:
    router = APIRouter(tags=["Config"])

    @router.get("/health/full", summary="Full system health (services, env, files)")
    async def health_full() -> Dict[str, Any]:
        return await health_full_status()
else:
    router = None  # type: ignore


# --------------------------------------------------------------------------------------
# הרצה ידנית לאבחון מקומי (לא חובה)
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    # לדיבוג מהיר: python utils/health_full.py
    out = asyncio.run(health_full_status())
    print(json.dumps(out, ensure_ascii=False, indent=2))


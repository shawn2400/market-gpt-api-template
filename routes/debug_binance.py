# routes/debug_binance.py
from __future__ import annotations
import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from utils.auth import require_api_key
from utils.binance_client import (
    get_futures_client,     # הפרוקסי (Lazy)
    fapi_ping,              # ping ל-Futures
    futures_mark_price,
    futures_exchange_info_safe,
)

router = APIRouter(
    prefix="/debug",
    tags=["Debug"],
    dependencies=[Depends(require_api_key)],
)

async def _try_server_time(client) -> Optional[int]:
    try:
        # נסה futures_time(); אם לא קיים – get_server_time()
        def _call() -> int:
            try:
                return int(client.futures_time().get("serverTime"))  # type: ignore
            except Exception:
                return int(client.get_server_time().get("serverTime"))
        return await asyncio.to_thread(_call)
    except Exception:
        return None

async def _test_order(client, symbol: str) -> Dict[str, Any]:
    # Dry-run (test order). חלק מ־python-binance מחייב מחרוזות לכמויות/מחירים.
    try:
        def _call():
            return client.futures_create_test_order(
                symbol=symbol.upper(),
                side="BUY",
                type="LIMIT",
                timeInForce="GTC",
                quantity="0.001",
                price="1000",
            )
        await asyncio.to_thread(_call)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.get("/binance-futures")
async def debug_binance_futures(symbol: str = Query("BTCUSDT", min_length=3, max_length=20)):
    """
    בדיקות חיבור ל-Binance Futures:
    - Ping + Exchange Info size
    - Server Time (לא קריטי)
    - Mark Price
    - ניסיון שליחת פקודת TEST (dry)
    """
    # ✅ Ping
    ping_ok = bool(fapi_ping())

    # ✅ Exchange Info (ברקע thread כדי לא לחסום לולאת ה-async)
    ex_info = await asyncio.to_thread(futures_exchange_info_safe)
    sym_count = len(ex_info.get("symbols") or []) if isinstance(ex_info, dict) else None

    # ✅ Server time (best-effort)
    client = get_futures_client()
    server_time = await _try_server_time(client)

    # ✅ Mark Price
    try:
        mark = futures_mark_price(symbol)
    except Exception as e:
        mark = f"error: {e}"

    # ✅ Test order
    test = await _test_order(client, symbol)

    return {
        "ping_ok": ping_ok,
        "symbols_count": sym_count,
        "server_time": server_time,
        "mark_price": mark,
        "test_order_ok": bool(test.get("ok")),
        "test_order_error": None if test.get("ok") else test.get("error"),
    }


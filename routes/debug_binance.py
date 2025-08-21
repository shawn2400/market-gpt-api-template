# routes/debug_binance.py
from fastapi import APIRouter, Depends
import asyncio

from utils.auth import require_bearer_token
from utils.binance_client import (
    get_client,
    ping_and_info,
    futures_mark_price,
    futures_exchange_info_safe,
    sync_server_time,
)

router = APIRouter(
    prefix="/debug",
    tags=["Debug"],
    dependencies=[Depends(require_bearer_token)]
)


@router.get("/binance-futures")
async def debug_binance_futures(symbol: str = "BTCUSDT"):
    """
    בדיקות חיבור ל-Binance Futures:
    - Ping + Exchange Info
    - Sync Server Time
    - Mark Price
    - ניסיון שליחת פקודת TEST
    """
    # ✅ Ping + Exchange Info
    ok = ping_and_info()

    # ✅ Sync server time (לא קריטי, רק לוג)
    try:
        sync_server_time()
    except Exception:
        pass

    # ✅ Mark Price
    prem = None
    try:
        prem = futures_mark_price(symbol)
    except Exception as e:
        prem = f"error: {e}"

    # ✅ Exchange Info count
    ex_info = await asyncio.to_thread(futures_exchange_info_safe)
    sym_count = (ex_info.get("symbols") and len(ex_info["symbols"])) if isinstance(ex_info, dict) else None

    # ✅ Test order (dry-run)
    client = get_client()
    test_order_ok = False
    test_order_err = None
    try:
        await asyncio.to_thread(
            client.futures_create_test_order,
            symbol=symbol,
            side="BUY",
            type="LIMIT",
            timeInForce="GTC",
            quantity="0.001",
            price="1000",
        )
        test_order_ok = True
    except Exception as e:
        test_order_err = str(e)

    return {
        "ping_ok": ok,
        "mark_price": prem,
        "symbols_count": sym_count,
        "test_order_ok": test_order_ok,
        "test_order_error": test_order_err,
    }


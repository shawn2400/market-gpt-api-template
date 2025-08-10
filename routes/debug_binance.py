# routes/debug_binance.py
from fastapi import APIRouter
import asyncio
import time

from utils.binance_client import get_client, ping_and_info, futures_mark_price, futures_exchange_info_safe
from utils.binance_client import sync_server_time

router = APIRouter(prefix="/debug", tags=["Debug"])

@router.get("/binance-futures")
async def debug_binance_futures(symbol: str = "BTCUSDT"):
    # 1) Ping + time sync
    ok = ping_and_info()
    try:
        sync_server_time()
    except Exception as e:
        pass

    # 2) Mark price (public)
    prem = futures_mark_price(symbol)

    # 3) Exchange info
    ex_info = await asyncio.to_thread(futures_exchange_info_safe)
    sym_count = (ex_info.get("symbols") and len(ex_info["symbols"])) if isinstance(ex_info, dict) else None

    # 4) Test order (לא מבצע טרייד אמיתי)
    client = get_client()
    test_order_resp = None
    test_err = None
    try:
        # הזמנת TEST; אם עוברת → מפתח/חתימה/Allowlist תקינים
        test_order_resp = await asyncio.to_thread(
            client.futures_create_test_order,
            symbol=symbol,
            side="BUY",
            type="LIMIT",
            timeInForce="GTC",
            quantity="0.001",
            price="1000",  # מחיר נמוך בכוונה כדי שלא יתבצע, זה TEST בכל מקרה
        )
    except Exception as e:
        test_err = str(e)

    return {
        "ping_ok": ok,
        "mark_price": prem,
        "symbols_count": sym_count,
        "test_order_ok": test_order_resp is None and test_err is None,  # ב-Binance test אין גוף החזרה → None זה תקין
        "test_order_error": test_err,
    }

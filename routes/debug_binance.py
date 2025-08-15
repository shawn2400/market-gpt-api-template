# routes/debug_binance.py
from fastapi import APIRouter, Depends, Header, Query, HTTPException
import asyncio

from utils.binance_client import (
    get_client, ping_and_info, futures_mark_price, futures_exchange_info_safe, sync_server_time
)
from utils import config as cfg

router = APIRouter(prefix="/debug", tags=["Debug"])

def auth_dep(
    authorization: str = Header(default=""),
    x_api_key: str = Header(default=""),
    token: str = Query(default="")
):
    expected = (getattr(cfg, "API_BEARER_TOKEN", "") or "").strip()
    bearer = ""
    if authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    if not bearer:
        bearer = (x_api_key or token or "").strip()
    if expected:
        if bearer != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")
    else:
        if not bearer:
            raise HTTPException(status_code=401, detail="Unauthorized")
    return True

@router.get("/binance-futures", dependencies=[Depends(auth_dep)])
async def debug_binance_futures(symbol: str = "BTCUSDT"):
    # 1) Ping + time sync
    ok = ping_and_info()
    try:
        sync_server_time()
    except Exception:
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
        test_order_resp = await asyncio.to_thread(
            client.futures_create_test_order,
            symbol=symbol,
            side="BUY",
            type="LIMIT",
            timeInForce="GTC",
            quantity="0.001",
            price="1000",
        )
    except Exception as e:
        test_err = str(e)

    return {
        "ping_ok": ok,
        "mark_price": prem,
        "symbols_count": sym_count,
        "test_order_ok": test_order_resp is None and test_err is None,
        "test_order_error": test_err,
    }


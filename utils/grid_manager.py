# בתוך utils/grid_manager.py
from utils.account_router import get_account_credentials
from utils.binance_client import get_futures_client
from utils.binance_spot_client import get_spot_client

async def cancel_grid(symbol: str, account_id: str = "main") -> Dict[str, Any]:
    symbol = symbol.upper().strip()

    creds = get_account_credentials(account_id)
    if not creds:
        return {"ok": False, "error": f"Account {account_id} not found"}

    client = None
    try:
        if creds["market"] == "futures":
            client = get_futures_client(creds["api_key"], creds["api_secret"])
            client.futures_cancel_all_open_orders(symbol=symbol)
        else:
            client = get_spot_client(creds["api_key"], creds["api_secret"])
            client.cancel_open_orders(symbol=symbol)
    except Exception as e:
        logger.warning({"event": "grid_cancel_orders_failed", "symbol": symbol, "err": str(e)})
        return {"ok": False, "error": str(e)}

    _del_state(symbol)
    return {"ok": True, "note": f"grid for {symbol} closed in account {account_id}"}






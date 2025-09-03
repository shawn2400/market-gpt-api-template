# utils/grid_manager.py
from __future__ import annotations
import logging
import time
from typing import Optional, Dict, Any

from utils.account_router import get_account_credentials
from utils.binance_client import get_futures_client
from utils.binance_spot_client import get_spot_client

logger = logging.getLogger("algogpt.grid_manager")

# ────────────────────────────────────────────────
# עזר
# ────────────────────────────────────────────────
_clients: Dict[str, Any] = {}

def _get_client(account_id: str, market: str):
    """
    טוען client לפי account_id (מה־accounts_config.json).
    שומר בזיכרון כדי לא ליצור מחדש כל קריאה.
    """
    key = f"{account_id}:{market}"
    if key in _clients:
        return _clients[key]

    creds = get_account_credentials(account_id)
    if not creds:
        raise RuntimeError(f"❌ Account {account_id} not found")

    if creds["market"] == "futures":
        client = get_futures_client(creds["api_key"], creds["api_secret"])
    elif creds["market"] == "spot":
        client = get_spot_client(creds["api_key"], creds["api_secret"])
    else:
        raise RuntimeError(f"❌ Unknown market type for account {account_id}")

    _clients[key] = client
    return client

# ────────────────────────────────────────────────
# פונקציות גריד
# ────────────────────────────────────────────────
async def start_grid_for_position(symbol: str, account_id: str = "main") -> Dict[str, Any]:
    """
    מפעיל Grid עבור פוזיציה קיימת בחשבון שנבחר.
    Futures → פותח SL/TP אמיתיים.
    Spot   → כרגע סימולציה בלבד.
    """
    try:
        creds = get_account_credentials(account_id)
        if not creds:
            return {"ok": False, "error": f"account {account_id} not found"}

        client = _get_client(account_id, creds["market"])
        sym = symbol.upper().strip()

        if creds["market"] == "futures":
            # דוגמה פשוטה: שולף balance / position
            pos = client.futures_position_information(symbol=sym)
            if not pos or float(pos[0].get("positionAmt", 0)) == 0:
                return {"ok": False, "error": "no open futures position"}

            entry = float(pos[0]["entryPrice"])
            amt = float(pos[0]["positionAmt"])
            side = "LONG" if amt > 0 else "SHORT"

            # SL/TP בסיסיים (לשדרוג בהמשך)
            sl = entry * (0.99 if side == "LONG" else 1.01)
            tp = entry * (1.02 if side == "LONG" else 0.98)

            try:
                # מצמיד SL
                client.futures_create_order(
                    symbol=sym,
                    side="SELL" if side == "LONG" else "BUY",
                    type="STOP_MARKET",
                    stopPrice=round(sl, 2),
                    quantity=abs(amt),
                    reduceOnly=True,
                )
                # מצמיד TP
                client.futures_create_order(
                    symbol=sym,
                    side="SELL" if side == "LONG" else "BUY",
                    type="TAKE_PROFIT_MARKET",
                    stopPrice=round(tp, 2),
                    quantity=abs(amt),
                    reduceOnly=True,
                )
            except Exception as e:
                return {"ok": False, "error": f"failed attach SL/TP: {e}"}

            return {
                "ok": True,
                "account_id": account_id,
                "market": "futures",
                "symbol": sym,
                "side": side,
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "qty": amt,
            }

        elif creds["market"] == "spot":
            price = client.get_symbol_ticker(symbol=sym)
            return {
                "ok": True,
                "account_id": account_id,
                "market": "spot",
                "symbol": sym,
                "note": "spot simulation only",
                "price": float(price["price"]) if price else None,
            }

    except Exception as e:
        logger.exception("start_grid_for_position_failed")
        return {"ok": False, "error": str(e)}

async def cancel_grid(symbol: str, account_id: str = "main") -> Dict[str, Any]:
    """
    מבטל את כל הפקודות הפתוחות עבור סימבול מסוים.
    """
    try:
        creds = get_account_credentials(account_id)
        if not creds:
            return {"ok": False, "error": f"account {account_id} not found"}

        client = _get_client(account_id, creds["market"])
        sym = symbol.upper().strip()

        if creds["market"] == "futures":
            client.futures_cancel_all_open_orders(symbol=sym)
        elif creds["market"] == "spot":
            client.cancel_open_orders(symbol=sym)

        return {"ok": True, "account_id": account_id, "symbol": sym}

    except Exception as e:
        logger.exception("cancel_grid_failed")
        return {"ok": False, "error": str(e)}

async def reconcile(symbol: str, account_id: str = "main") -> Dict[str, Any]:
    """
    בודק אם יש פוזיציה מול פקודות גריד ומעדכן.
    """
    try:
        creds = get_account_credentials(account_id)
        if not creds:
            return {"ok": False, "error": f"account {account_id} not found"}

        client = _get_client(account_id, creds["market"])
        sym = symbol.upper().strip()

        if creds["market"] == "futures":
            pos = client.futures_position_information(symbol=sym)
            oo = client.futures_get_open_orders(symbol=sym)
            return {
                "ok": True,
                "market": "futures",
                "account_id": account_id,
                "pos": pos,
                "open_orders": oo,
            }

        elif creds["market"] == "spot":
            bal = client.get_asset_balance(asset=sym.replace("USDT", ""))
            oo = client.get_open_orders(symbol=sym)
            return {
                "ok": True,
                "market": "spot",
                "account_id": account_id,
                "balance": bal,
                "open_orders": oo,
            }

    except Exception as e:
        logger.exception("reconcile_failed")
        return {"ok": False, "error": str(e)}





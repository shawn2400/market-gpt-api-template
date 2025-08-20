# utils/binance_client.py
from __future__ import annotations
import os
import logging
from binance.client import Client

# --- קונפיגורציה מתוך ENV ---
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
USE_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes")

logger = logging.getLogger("algogpt.binance")

if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    raise RuntimeError("Missing BINANCE_API_KEY or BINANCE_API_SECRET in environment")

# --- יצירת Binance Client ---
binance_client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

# מעבר ל־Testnet אם צריך
if USE_TESTNET:
    logger.warning("⚠️ Using Binance TESTNET endpoints")
    binance_client.API_URL = "https://testnet.binance.vision/api"
    binance_client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
else:
    binance_client.API_URL = "https://api.binance.com/api"
    binance_client.FUTURES_URL = "https://fapi.binance.com/fapi"

# =====================================================
#                SPOT FUNCTIONS
# =====================================================
def spot_new_order(symbol: str, side: str, type: str, quantity: float, price: float = None, timeInForce: str = "GTC"):
    """
    שולח פקודת SPOT ל־Binance.
    side: BUY / SELL
    type: LIMIT / MARKET
    """
    try:
        params = {
            "symbol": symbol,
            "side": side,
            "type": type,
            "quantity": quantity,
        }
        if type == "LIMIT" and price:
            params["price"] = price
            params["timeInForce"] = timeInForce

        order = binance_client.create_order(**params)
        return order
    except Exception as e:
        logger.exception(f"Binance spot_new_order failed: {e}")
        raise

def spot_balance(asset: str = "USDT"):
    try:
        balances = binance_client.get_asset_balance(asset=asset)
        if balances:
            return float(balances.get("free", 0))
        return 0.0
    except Exception as e:
        logger.exception(f"Binance spot_balance failed: {e}")
        return 0.0

# =====================================================
#                FUTURES FUNCTIONS
# =====================================================
def futures_new_order(symbol: str, side: str, type: str, quantity: float, price: float = None, timeInForce: str = "GTC"):
    """
    שולח פקודת FUTURES ל־Binance.
    side: BUY / SELL
    type: LIMIT / MARKET / STOP
    """
    try:
        params = {
            "symbol": symbol,
            "side": side,
            "type": type,
            "quantity": quantity,
        }
        if type == "LIMIT" and price:
            params["price"] = price
            params["timeInForce"] = timeInForce

        order = binance_client.futures_create_order(**params)
        return order
    except Exception as e:
        logger.exception(f"Binance futures_new_order failed: {e}")
        raise

def futures_balance(asset: str = "USDT"):
    try:
        balances = binance_client.futures_account_balance()
        for b in balances:
            if b["asset"] == asset:
                return float(b["balance"])
        return 0.0
    except Exception as e:
        logger.exception(f"Binance futures_balance failed: {e}")
        return 0.0

def futures_position(symbol: str):
    try:
        positions = binance_client.futures_position_information(symbol=symbol)
        if positions:
            return positions[0]
        return None
    except Exception as e:
        logger.exception(f"Binance futures_position failed: {e}")
        return None

# =====================================================
#                GRID TRADING HELPERS
# =====================================================
def grid_orders(symbol: str, side: str, start_price: float, end_price: float, steps: int, quantity: float):
    """
    מייצר פקודות גריד בין start_price ל־end_price.
    side: BUY / SELL
    """
    try:
        if steps < 2:
            raise ValueError("steps must be >= 2")

        price_step = (end_price - start_price) / (steps - 1)
        orders = []

        for i in range(steps):
            price = round(start_price + i * price_step, 2)
            order = {
                "symbol": symbol,
                "side": side,
                "type": "LIMIT",
                "quantity": quantity,
                "price": price,
                "timeInForce": "GTC",
            }
            orders.append(order)

        return orders
    except Exception as e:
        logger.exception(f"Binance grid_orders failed: {e}")
        return []







































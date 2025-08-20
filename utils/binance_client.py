# utils/binance_client.py
from __future__ import annotations
import os
import logging
import time
from typing import Any, Callable
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

logger = logging.getLogger("algogpt.binance")

# --- ENV config ---
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
USE_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes")


# =====================================================
# Client factory
# =====================================================
def get_client() -> Client:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise RuntimeError("Missing BINANCE_API_KEY or BINANCE_API_SECRET in environment")

    client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    if USE_TESTNET:
        logger.warning("⚠️ Using Binance TESTNET endpoints")
        client.API_URL = "https://testnet.binance.vision/api"
        client.FUTURES_URL = "https://testnet.binancefuture.com/fapi/v1"
    else:
        client.API_URL = "https://api.binance.com/api"
        client.FUTURES_URL = "https://fapi.binance.com/fapi/v1"

    return client


# =====================================================
# Retry helper (used by trader/backtester)
# =====================================================
def retry_call(fn: Callable[[], Any], label: str, retries: int = 3, delay: float = 0.5) -> Any:
    for i in range(retries):
        try:
            return fn()
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.warning(f"[Binance] {label} failed ({i+1}/{retries}): {e}")
            time.sleep(delay)
        except Exception as e:
            logger.error(f"[Binance] {label} unexpected error: {e}")
            time.sleep(delay)
    raise RuntimeError(f"[Binance] {label} failed after {retries} retries")


# =====================================================
# Futures Exchange Info cache
# =====================================================
_futures_exchange_info_cache: dict[str, Any] | None = None

def futures_exchange_info_safe() -> dict[str, Any]:
    global _futures_exchange_info_cache
    if _futures_exchange_info_cache is not None:
        return _futures_exchange_info_cache

    client = get_client()
    info = retry_call(lambda: client.futures_exchange_info(), "futures_exchange_info")
    if isinstance(info, dict):
        _futures_exchange_info_cache = info
    return info


# =====================================================
# Simple Spot / Futures wrappers
# =====================================================
def spot_balance(asset: str = "USDT") -> float:
    client = get_client()
    balances = retry_call(lambda: client.get_asset_balance(asset=asset), f"spot_balance({asset})")
    return float(balances.get("free", 0) or 0.0)


def futures_balance(asset: str = "USDT") -> float:
    client = get_client()
    balances = retry_call(lambda: client.futures_account_balance(), "futures_account_balance")
    for b in balances:
        if b.get("asset") == asset:
            return float(b.get("balance", 0))
    return 0.0


def futures_position(symbol: str) -> dict[str, Any] | None:
    client = get_client()
    positions = retry_call(lambda: client.futures_position_information(symbol=symbol.upper()),
                           f"futures_position({symbol})")
    return positions[0] if positions else None








































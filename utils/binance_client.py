# utils/binance_client.py
from __future__ import annotations
import os, time, logging
from typing import Any, Callable, Optional, Dict, List
import httpx
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

logger = logging.getLogger("algogpt.binance")

# ENV
BINANCE_API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
BINANCE_API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
USE_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() in ("1","true","yes")
BINANCE_FAPI_BASE = (os.getenv("BINANCE_FAPI_BASE") or "https://fapi.binance.com").rstrip("/")
BINANCE_HTTP_BASE = (os.getenv("BINANCE_HTTP_BASE") or "https://api.binance.com").rstrip("/")
SUPPRESS_BINANCE_WARNINGS = os.getenv("SUPPRESS_BINANCE_WARNINGS", "0").lower() in ("1","true","yes")

# Client
def get_client() -> Client:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise RuntimeError("❌ Missing BINANCE_API_KEY / BINANCE_API_SECRET")

    client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    if USE_TESTNET:
        logger.warning("⚠️ Using Binance TESTNET endpoints")
        client.API_URL = "https://testnet.binance.vision/api"
        client.FUTURES_URL = "https://testnet.binancefuture.com/fapi/v1"
    else:
        # ✅ LIVE endpoints
        client.API_URL = f"{BINANCE_HTTP_BASE}/api"
        client.FUTURES_URL = f"{BINANCE_FAPI_BASE}/fapi/v1"

    return client

# retry wrapper
def retry_call(fn: Callable[[], Any], label: str, retries: int = 5, delay: float = 0.5) -> Any:
    last_exc: Optional[Exception] = None
    for i in range(retries):
        try:
            return fn()
        except (BinanceAPIException, BinanceRequestException, httpx.HTTPError) as e:
            last_exc = e
            level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
            logger.log(level, f"[Binance] {label} failed ({i+1}/{retries}): {e}")
            time.sleep(delay)
        except Exception as e:
            last_exc = e
            logger.error(f"[Binance] {label} unexpected error: {e}")
            time.sleep(delay)
    raise RuntimeError(f"[Binance] {label} failed after {retries} retries: {last_exc}")




































































































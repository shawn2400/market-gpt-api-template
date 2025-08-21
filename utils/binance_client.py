# utils/binance_client.py
from __future__ import annotations

import os
import json
import time
import logging
from typing import Any, Callable, Optional, Dict, List

import httpx
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

logger = logging.getLogger("algogpt.binance")

# =========================
# ENV / Config
# =========================
BINANCE_API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
BINANCE_API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
USE_TESTNET = (os.getenv("BINANCE_TESTNET", "false").strip().lower() in ("1", "true", "yes"))

# בסיסי FAPI (רוטציה נגד חסימות/Redirect)
_BINANCE_FAPI_BASES: List[str] = [
    (os.getenv("BINANCE_FAPI_BASE") or "https://fapi.binance.com").rstrip("/"),
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
]

_DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "4.0"))
_RETRY_STATUSES = {418, 429, 500, 502, 503, 504}


# =========================
# Client factory (לקריאות Signed/Priv)
# =========================
def get_client() -> Client:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise RuntimeError("Missing BINANCE_API_KEY or BINANCE_API_SECRET in environment")

    client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    if USE_TESTNET:
        logger.warning("⚠️ Using Binance TESTNET endpoints")
        # spot testnet
        client.API_URL = "https://testnet.binance.vision/api"
        # futures testnet
        client.FUTURES_URL = "https://testnet.binancefuture.com/fapi/v1"
    else:
        client.API_URL = "https://api.binance.com/api"
        client.FUTURES_URL = "https://fapi.binance.com/fapi/v1"

    return client


# =========================
# Retry helper
# =========================
def retry_call(fn: Callable[[], Any], label: str, retries: int = 3, delay: float = 0.5) -> Any:
    last_exc: Optional[Exception] = None
    for i in range(retries):
        try:
            return fn()
        except (BinanceAPIException, BinanceRequestException, httpx.HTTPError) as e:
            last_exc = e
            logger.warning(f"[Binance] {label} failed ({i+1}/{retries}): {e}")
            time.sleep(delay)
        except Exception as e:
            last_exc = e
            logger.error(f"[Binance] {label} unexpected error: {e}")
            time.sleep(delay)
    raise RuntimeError(f"[Binance] {label} failed after {retries} retries: {last_exc}")


# =========================
# Futures Exchange Info cache
# =========================
_futures_exchange_info_cache: Optional[Dict[str, Any]] = None

def futures_exchange_info_safe() -> Dict[str, Any]:
    global _futures_exchange_info_cache
    if _futures_exchange_info_cache is not None:
        return _futures_exchange_info_cache

    client = get_client()
    info = retry_call(lambda: client.futures_exchange_info(), "futures_exchange_info")
    if isinstance(info, dict):
        _futures_exchange_info_cache = info
    return info


# =========================
# Spot & Futures helpers (Priv)
# =========================
def spot_balance(asset: str = "USDT") -> float:
    client = get_client()
    balances = retry_call(lambda: client.get_asset_balance(asset=asset), f"spot_balance({asset})")
    return float(balances.get("free", 0) or 0.0)


def futures_balance(asset: str = "USDT") -> float:
    client = get_client()
    balances = retry_call(lambda: client.futures_account_balance(), "futures_account_balance")
    for b in balances:
        if b.get("asset") == asset:
            return float(b.get("balance", 0) or 0.0)
    return 0.0


def futures_position(symbol: str) -> Optional[Dict[str, Any]]:
    client = get_client()
    positions = retry_call(lambda: client.futures_position_information(symbol=symbol.upper()),
                           f"futures_position({symbol})")
    return positions[0] if positions else None


def futures_open_positions() -> List[Dict[str, Any]]:
    client = get_client()
    positions = retry_call(lambda: client.futures_position_information(), "futures_open_positions")
    out: List[Dict[str, Any]] = []
    for p in positions:
        amt = float(p.get("positionAmt", 0) or 0.0)
        if abs(amt) > 0:
            side = "LONG" if amt > 0 else "SHORT"
            out.append({
                "symbol": p.get("symbol"),
                "side": side,
                "entryPrice": float(p.get("entryPrice", 0) or 0.0),
                "unrealizedPnl": float(p.get("unRealizedProfit", 0) or 0.0),
                "positionAmt": amt,
                "leverage": int(p.get("leverage", 0) or 0),
                "marginType": (p.get("marginType") or "").upper(),
            })
    return out


def ping_and_info() -> bool:
    client = get_client()
    try:
        retry_call(lambda: client.ping(), "ping")
        retry_call(lambda: client.futures_exchange_info(), "exchange_info")
        return True
    except Exception as e:
        logger.error(f"[Binance] ping_and_info failed: {e}")
        return False


# =========================
# Public Futures Mark Price (Robust)
# =========================
def _looks_like_json(txt: str) -> bool:
    if not txt:
        return False
    t = txt.lstrip()
    return t.startswith("{") or t.startswith("[")


def futures_mark_price_dict(symbol: str, tries: int = 3) -> Dict[str, Any]:
    """
    מביא Mark Price מ-/fapi/v1/premiumIndex בצורה חסינה:
    - follow_redirects=False כדי לא "ליפול" לדף HTML
    - רוטציית דומיינים (fapi, fapi1, fapi2, fapi3)
    - בדיקת Content-Type + מבנה JSON
    - אם כל הבקשות נכשלו: fallback למטמון WS (אם זמין)
    """
    if USE_TESTNET:
        # Testnet לא מספק premiumIndex תקני; נשתמש בלקוח הספרייה
        client = get_client()
        data = retry_call(lambda: client.futures_mark_price(symbol=symbol.upper()),
                          f"futures_mark_price({symbol})/testnet")
        return data if isinstance(data, dict) else {"symbol": symbol.upper(), "markPrice": str(float(data))}

    sym = symbol.upper().strip()
    last_err: Optional[str] = None

    headers = {
        "Accept": "application/json",
        "User-Agent": "AlgoGPT/2 binance-client",
    }

    for attempt in range(1, tries + 1):
        for base in _BINANCE_FAPI_BASES:
            url = f"{base}/fapi/v1/premiumIndex"
            try:
                with httpx.Client(timeout=_DEFAULT_TIMEOUT, http2=True, follow_redirects=False) as client:
                    r = client.get(url, params={"symbol": sym}, headers=headers)
                if r.status_code != 200:
                    # רוטציה במצבי 3xx/5xx או קודי rate/ban
                    if (300 <= r.status_code < 400) or (r.status_code in _RETRY_STATUSES):
                        last_err = f"HTTP {r.status_code} from {base}"
                        continue
                    # 4xx אחר → שגיאה מפורטת
                    raise RuntimeError(f"HTTP {r.status_code} from {base}: {r.text[:200]}")

                ct = (r.headers.get("Content-Type") or "")
                body = r.text or ""
                if ("application/json" not in ct) or (not _looks_like_json(body)):
                    last_err = f"Non-JSON from {base}: {ct} / {body[:120]}"
                    continue

                data = r.json()
                if not isinstance(data, dict) or "markPrice" not in data:
                    raise RuntimeError(f"JSON missing markPrice from {base}: {body[:200]}")
                return data

            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                # נמשיך לדומיין הבא

        # backoff קטן בין סבבים
        time.sleep(0.35 * attempt)

    # Fallback: WS cache
    try:
        from utils.ws_fallback import LAST_PRICE_CACHE  # type: ignore
        rec = LAST_PRICE_CACHE.get(sym)
        if rec and "price" in rec:
            return {"symbol": sym, "markPrice": str(rec["price"]), "ts": rec.get("ts")}
    except Exception:
        pass

    raise RuntimeError(f"[Binance] futures_mark_price_dict({sym}) failed after {tries} tries: {last_err}")


def futures_mark_price(symbol: str) -> float:
    """
    API נוח שמחזיר float בלבד. משתמש ב-futures_mark_price_dict.
    """
    data = futures_mark_price_dict(symbol)
    try:
        return float(data.get("markPrice") or 0.0)
    except Exception:
        # ניסוי המרה קשיח אחרון
        return float(str(data.get("markPrice", "0")).strip() or 0.0)










































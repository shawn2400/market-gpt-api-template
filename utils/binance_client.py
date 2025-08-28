# utils/binance_client.py
from __future__ import annotations

import os
import time
import hmac
import json
import math
import hashlib
import logging
from typing import Any, Dict, Optional, Tuple, List
from threading import Event, Thread

import httpx
from httpx import Limits

logger = logging.getLogger("algogpt.binance")

# ============ ENV & Config ============
def _clean_env(s: Optional[str]) -> str:
    """
    Remove CR/LF/TAB and surrounding quotes/spaces. Binance keys must be one line, 64/64.
    """
    if not s:
        return ""
    s = s.strip().strip('"').replace("\r", "").replace("\n", "").replace("\t", "")
    return s

BINANCE_API_KEY = _clean_env(os.getenv("BINANCE_API_KEY"))
BINANCE_API_SECRET = _clean_env(os.getenv("BINANCE_API_SECRET"))
USE_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes")

FAPI_BASE = (
    os.getenv("BINANCE_FUTURES_HTTP_BASE")
    or os.getenv("BINANCE_FAPI_BASE")
    or ("https://testnet.binancefuture.com" if USE_TESTNET else "https://fapi.binance.com")
).rstrip("/")

HTTP_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
RECV_WINDOW = int(float(os.getenv("BINANCE_RECV_WINDOW", "20000")))
MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))
BACKOFF_BASE = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))  # seconds

SUPPRESS_WARN = os.getenv("SUPPRESS_BINANCE_WARNINGS", "1").lower() in ("1", "true", "yes")
if SUPPRESS_WARN:
    logging.getLogger("httpx").setLevel(logging.WARNING)


# =============== HTTP Client Wrap ===============
class _BinanceFutures:
    """
    Robust Binance Futures REST client (sync):
      - HMAC-SHA256 signing
      - Timestamp drift handling (-1021) via time sync
      - Retries with backoff (429/418/5xx)
      - Public & signed helpers
      - Basic symbol filters normalization (price/qty/notional)
    """

    def __init__(self) -> None:
        self.api_key = BINANCE_API_KEY
        self.api_secret = BINANCE_API_SECRET
        self.base = FAPI_BASE
        self.timeout = HTTP_TIMEOUT
        self.recv_window = RECV_WINDOW
        self.max_retries = MAX_RETRIES
        self.backoff_base = BACKOFF_BASE
        self._time_offset_ms = 0  # server_time - local_time
        self._exchange_info_cache: Optional[Dict[str, Any]] = None

        self._client = httpx.Client(
            timeout=self.timeout,
            http2=False,
            limits=Limits(max_keepalive_connections=20, max_connections=50),
        )

        # Key length sanity (do not raise to allow public endpoints in degraded mode)
        if (self.api_key and len(self.api_key) != 64) or (self.api_secret and len(self.api_secret) != 64):
            logger.error("[Binance] API keys invalid length (must be 64/64).")

    # ---- Utilities ----
    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _server_time_ms(self) -> int:
        r = self._client.get(f"{self.base}/fapi/v1/time")
        r.raise_for_status()
        return int(r.json()["serverTime"])

    def _sync_time(self) -> None:
        try:
            server_ms = self._server_time_ms()
            local_ms = self._now_ms()
            self._time_offset_ms = server_ms - local_ms
            logger.info(f"[Binance] Time synced. Offset={self._time_offset_ms} ms")
        except Exception as e:
            logger.error(f"[Binance] Time sync failed: {e}")

    def _headers(self) -> Dict[str, str]:
        return {"X-MBX-APIKEY": self.api_key} if self.api_key else {}

    def _sign(self, params: Dict[str, Any]) -> Tuple[str, str]:
        # Sort keys for deterministic signing
        items = [f"{k}={params[k]}" for k in sorted(params.keys())]
        query = "&".join(items)
        signature = hmac.new(
            self.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return query, signature

    def _backoff(self, attempt: int) -> float:
        return min(self.backoff_base * (2 ** attempt), 4.5)

    # ---- Core Requestors ----
    def _public_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base}/{path.lstrip('/')}"
        for attempt in range(self.max_retries):
            try:
                r = self._client.get(url, params=params or {})
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                body = e.response.text
                logger.error(f"[Binance] public GET {path} failed ({status}): {body[:200]}")
                if status >= 500:
                    time.sleep(self._backoff(attempt))
                    continue
                raise
            except Exception as e:
                logger.error(f"[Binance] public GET {path} exception: {e}")
                time.sleep(self._backoff(attempt))
        raise RuntimeError(f"[Binance] public GET {path} exhausted retries")

    def _signed(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Binance API keys missing")

        params = dict(params or {})
        params.setdefault("timestamp", self._now_ms() + self._time_offset_ms)
        params.setdefault("recvWindow", self.recv_window)

        url = f"{self.base}/{path.lstrip('/')}"

        for attempt in range(self.max_retries):
            query, sig = self._sign(params)
            full_url = f"{url}?{query}&signature={sig}"
            try:
                r = self._client.request(method.upper(), full_url, headers=self._headers())

                # Backoff on rate-limit/ban and 5xx
                if r.status_code in (418, 429) or r.status_code >= 500:
                    logger.warning(f"[Binance] signed {method} {path} rate/5xx ({r.status_code}): {r.text[:200]}")
                    time.sleep(self._backoff(attempt))
                    continue

                # Handle timestamp drift (-1021) by syncing time and retrying
                if r.status_code == 400:
                    try:
                        data = r.json()
                        code = data.get("code")
                    except Exception:
                        code = None
                    if code == -1021:
                        logger.warning("[Binance] -1021 (timestamp). Syncing time and retrying...")
                        self._sync_time()
                        params["timestamp"] = self._now_ms() + self._time_offset_ms
                        continue

                r.raise_for_status()
                return r.json()

            except httpx.HTTPStatusError as e:
                try:
                    err = e.response.json()
                except Exception:
                    err = {"raw": e.response.text}
                logger.error(
                    f"[Binance] signed {method} {path} failed {e.response.status_code}: {json.dumps(err)[:300]}"
                )
                if 400 <= e.response.status_code < 500:
                    # Most likely -2015 invalid key/IP/permissions or signature issues: bubble up
                    raise
                time.sleep(self._backoff(attempt))

            except Exception as e:
                logger.error(f"[Binance] signed {method} {path} exception: {e}")
                time.sleep(self._backoff(attempt))

        raise RuntimeError(f"[Binance] signed {method} {path} exhausted retries")

    # ========= Public Endpoints =========
    def ping(self) -> bool:
        try:
            self._public_get("fapi/v1/ping")
            return True
        except Exception as e:
            logger.error(f"[Binance] fapi_ping failed: {e}")
            return False

    def server_time(self) -> int:
        return self._server_time_ms()

    def premium_index(self, symbol: str) -> Dict[str, Any]:
        return self._public_get("fapi/v1/premiumIndex", {"symbol": symbol.upper()})

    def mark_price(self, symbol: str) -> Optional[float]:
        try:
            data = self.premium_index(symbol)
            mp = data.get("markPrice")
            if mp is not None:
                return float(mp)
        except Exception as e:
            logger.error(f"[Binance] mark_price error {symbol}: {e}")
        return None

    def exchange_info(self, force_refresh: bool = False) -> Dict[str, Any]:
        if self._exchange_info_cache is not None and not force_refresh:
            return self._exchange_info_cache
        self._exchange_info_cache = self._public_get("fapi/v1/exchangeInfo")
        return self._exchange_info_cache

    def symbol_info(self, symbol: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        info = self.exchange_info(force_refresh=force_refresh)
        for s in info.get("symbols", []):
            if s.get("symbol") == symbol.upper():
                return s
        return None

    # ========= Signed Account Endpoints =========
    def position_risk(self) -> List[dict]:
        try:
            res = self._signed("GET", "fapi/v2/positionRisk")
            return res if isinstance(res, list) else []
        except Exception as e:
            logger.error(f"[Binance] position_risk failed: {e}")
            return []

    def balance(self) -> List[dict]:
        try:
            res = self._signed("GET", "fapi/v2/balance")
            return res if isinstance(res, list) else []
        except Exception as e:
            logger.error(f"[Binance] balance failed: {e}")
            return []

    # ======== Filters / Normalization ========
    def _symbol_filters(self, symbol: str) -> Dict[str, Any]:
        info = self.symbol_info(symbol, force_refresh=False)
        if not info:
            raise ValueError(f"Symbol {symbol} not found in exchangeInfo")
        return {f["filterType"]: f for f in info.get("filters", [])}

    @staticmethod
    def _snap(val: float, step_: float) -> float:
        if step_ <= 0:
            return val
        return math.floor(val / step_) * step_

    def _normalize_px_qty(
        self, symbol: str, price: Optional[float], quantity: float
    ) -> Tuple[Optional[float], float]:
        fs = self._symbol_filters(symbol)
        lot = fs.get("LOT_SIZE", {})
        step = float(lot.get("stepSize", "0.00000001"))
        min_qty = float(lot.get("minQty", "0"))

        notional = fs.get("MIN_NOTIONAL") or fs.get("NOTIONAL") or {}
        min_notional = float(notional.get("minNotional", "0")) if notional else 0.0

        pf = fs.get("PRICE_FILTER", {})
        tick = float(pf.get("tickSize", "0.00000001"))

        q = self._snap(float(quantity), step)
        if q < min_qty:
            raise ValueError(f"Quantity {q} < minQty {min_qty} for {symbol}")

        p = None
        if price is not None:
            p = self._snap(float(price), tick)
            if p <= 0:
                raise ValueError("Price must be > 0")

        if min_notional and p is not None and p * q < min_notional:
            raise ValueError(f"Order notional {p*q:.8f} < minNotional {min_notional} for {symbol}")

        return p, q

    # ==================== Account/Mode ====================
    def set_position_mode(self, hedge: bool) -> Any:
        return self.signed_post("fapi/v1/positionSide/dual", {"dualSidePosition": str(hedge).lower()})

    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> Any:
        mt = margin_type.upper()
        if mt not in ("ISOLATED", "CROSSED"):
            raise ValueError("margin_type must be ISOLATED or CROSSED")
        return self.signed_post("fapi/v1/marginType", {"symbol": symbol.upper(), "marginType": mt})

    def set_leverage(self, symbol: str, leverage: int) -> Any:
        lev = int(leverage)
        if not (1 <= lev <= 125):
            raise ValueError("leverage must be 1..125")
        return self.signed_post("fapi/v1/leverage", {"symbol": symbol.upper(), "leverage": lev})

    # ======================= Order APIs =======================
    def place_limit_order(
        self,
        symbol: str,
        side: str,                 # "BUY" / "SELL"
        quantity: float,
        price: float,
        *,
        post_only: bool = True,    # GTX
        reduce_only: bool = False,
        position_side: Optional[str] = None,  # "LONG"/"SHORT" when Hedge
        new_client_order_id: Optional[str] = None,
        time_in_force: Optional[str] = None,  # overrides post_only if given
    ) -> Dict[str, Any]:
        symbol = symbol.upper()
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")

        p, q = self._normalize_px_qty(symbol, price, quantity)
        tif = time_in_force or ("GTX" if post_only else "GTC")

        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "timeInForce": tif,
            "quantity": f"{q:.20f}",
            "price": f"{p:.20f}",
            "reduceOnly": str(bool(reduce_only)).lower(),
            "recvWindow": self.recv_window,
        }
        if position_side:
            ps = position_side.upper()
            if ps not in ("LONG", "SHORT", "BOTH"):
                raise ValueError("position_side must be LONG/SHORT/BOTH")
            params["positionSide"] = ps
        if new_client_order_id:
            params["newClientOrderId"] = new_client_order_id[:36]

        return self.signed_post("fapi/v1/order", params)

    def place_stop_limit(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        limit_price: float,
        *,
        working_type: str = "MARK_PRICE",
        reduce_only: bool = False,
        position_side: Optional[str] = None,
        post_only: bool = True,
        price_protect: bool = True,
        new_client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        symbol = symbol.upper()
        side = side.upper()
        p_limit, q = self._normalize_px_qty(symbol, limit_price, quantity)
        p_stop, _ = self._normalize_px_qty(symbol, stop_price, q)

        params = {
            "symbol": symbol,
            "side": side,
            "type": "STOP",
            "timeInForce": "GTX" if post_only else "GTC",
            "quantity": f"{q:.20f}",
            "price": f"{p_limit:.20f}",
            "stopPrice": f"{p_stop:.20f}",
            "workingType": working_type,
            "priceProtect": str(bool(price_protect)).lower(),
            "reduceOnly": str(bool(reduce_only)).lower(),
            "recvWindow": self.recv_window,
        }
        if position_side:
            params["positionSide"] = position_side.upper()
        if new_client_order_id:
            params["newClientOrderId"] = new_client_order_id[:36]

        return self.signed_post("fapi/v1/order", params)

    def place_stop_market(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        *,
        working_type: str = "MARK_PRICE",
        reduce_only: bool = False,
        position_side: Optional[str] = None,
        price_protect: bool = True,
        new_client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        symbol = symbol.upper()
        side = side.upper()
        _, q = self._normalize_px_qty(symbol, None, quantity)
        p_stop, _ = self._normalize_px_qty(symbol, stop_price, q)

        params = {
            "symbol": symbol,
            "side": side,
            "type": "STOP_MARKET",
            "stopPrice": f"{p_stop:.20f}",
            "workingType": working_type,
            "priceProtect": str(bool(price_protect)).lower(),
            "reduceOnly": str(bool(reduce_only)).lower(),
            "quantity": f"{q:.20f}",
            "recvWindow": self.recv_window,
        }
        if position_side:
            params["positionSide"] = position_side.upper()
        if new_client_order_id:
            params["newClientOrderId"] = new_client_order_id[:36]

        return self.signed_post("fapi/v1/order", params)

    def cancel_order(self, symbol: str, order_id: Optional[int] = None, client_oid: Optional[str] = None) -> Dict[str, Any]:
        if not order_id and not client_oid:
            raise ValueError("Provide order_id or client_oid")
        params = {"symbol": symbol.upper()}
        if order_id:
            params["orderId"] = int(order_id)
        if client_oid:
            params["origClientOrderId"] = client_oid
        return self.signed_delete("fapi/v1/order", params)

    def cancel_all(self, symbol: str) -> Dict[str, Any]:
        return self.signed_delete("fapi/v1/allOpenOrders", {"symbol": symbol.upper()})

    def get_order(self, symbol: str, order_id: Optional[int] = None, client_oid: Optional[str] = None) -> Dict[str, Any]:
        if not order_id and not client_oid:
            raise ValueError("Provide order_id or client_oid")
        params = {"symbol": symbol.upper()}
        if order_id:
            params["orderId"] = int(order_id)
        if client_oid:
            params["origClientOrderId"] = client_oid
        return self.signed_get("fapi/v1/order", params)

    # ---- generic signed wrappers ----
    def signed_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._signed("GET", path, params)

    def signed_post(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._signed("POST", path, params)

    def signed_delete(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._signed("DELETE", path, params)

    # ----- User Data Stream (Futures) -----
    def user_stream_start(self) -> str:
        """Create a listenKey for futures user data stream."""
        url = f"{self.base}/fapi/v1/listenKey"
        r = self._client.post(url, headers=self._headers())
        r.raise_for_status()
        lk = r.json().get("listenKey")
        if not lk:
            raise RuntimeError("Failed to obtain listenKey")
        logger.info(f"[Binance] listenKey created: {lk[:8]}... (masked)")
        return lk

    def user_stream_keepalive(self, listen_key: str) -> None:
        """Keep the listenKey alive (call at least once every 30 minutes)."""
        url = f"{self.base}/fapi/v1/listenKey"
        r = self._client.put(url, headers=self._headers(), params={"listenKey": listen_key})
        if r.status_code == 200:
            logger.debug("[Binance] listenKey keepalive OK")
        else:
            logger.warning(f"[Binance] listenKey keepalive status {r.status_code}: {r.text[:200]}")

    def user_stream_close(self, listen_key: str) -> None:
        """Close the listenKey (cleanup)."""
        url = f"{self.base}/fapi/v1/listenKey"
        r = self._client.delete(url, headers=self._headers(), params={"listenKey": listen_key})
        if r.status_code == 200:
            logger.info("[Binance] listenKey closed")
        else:
            logger.warning(f"[Binance] listenKey close status {r.status_code}: {r.text[:200]}")


# Singleton
_CLIENT = _BinanceFutures()

# Background keepalive management for listenKey
_listen_key: Optional[str] = None
_lk_thread_stop = Event()
_lk_thread: Optional[Thread] = None

def start_user_stream_keepalive(period_sec: int = 1800) -> str:
    """
    Start user-stream (listenKey) and keep it alive in background.
    period_sec=1800 (30m). Binance דורשת רענון < 60m.
    """
    global _listen_key, _lk_thread, _lk_thread_stop
    if _listen_key:
        return _listen_key
    _listen_key = _CLIENT.user_stream_start()

    def _loop():
        while not _lk_thread_stop.wait(timeout=period_sec):
            try:
                _CLIENT.user_stream_keepalive(_listen_key)
            except Exception as e:
                logger.warning(f"[Binance] listenKey keepalive error: {e}")

    _lk_thread_stop.clear()
    _lk_thread = Thread(target=_loop, name="binance-listenKey-keepalive", daemon=True)
    _lk_thread.start()
    return _listen_key

def stop_user_stream():
    """Stop background keepalive and close the listenKey."""
    global _listen_key, _lk_thread, _lk_thread_stop
    try:
        _lk_thread_stop.set()
        if _lk_thread and _lk_thread.is_alive():
            _lk_thread.join(timeout=5)
        if _listen_key:
            try:
                _CLIENT.user_stream_close(_listen_key)
            except Exception as e:
                logger.warning(f"[Binance] close listenKey error: {e}")
    finally:
        _listen_key = None
        _lk_thread = None
        _lk_thread_stop.clear()


# ======================== Public Wrappers ========================
def fapi_ping() -> bool:
    return _CLIENT.ping()

def futures_mark_price(symbol: str) -> Optional[float]:
    return _CLIENT.mark_price(symbol)

_futures_exchange_info_cache_shadow: Optional[Dict[str, Any]] = None
def futures_exchange_info_safe(force_refresh: bool = False) -> Dict[str, Any]:
    global _futures_exchange_info_cache_shadow
    if _futures_exchange_info_cache_shadow is not None and not force_refresh:
        return _futures_exchange_info_cache_shadow
    _futures_exchange_info_cache_shadow = _CLIENT.exchange_info(force_refresh=force_refresh)
    return _futures_exchange_info_cache_shadow

def get_symbol_info(symbol: str, force_refresh: bool = False) -> Optional[dict]:
    return _CLIENT.symbol_info(symbol, force_refresh=force_refresh)

def futures_open_positions() -> List[dict]:
    return _CLIENT.position_risk()

def futures_balance() -> List[dict]:
    return _CLIENT.balance()

# Account/mode wrappers
def set_position_mode(hedge: bool) -> Any:
    return _CLIENT.set_position_mode(hedge)

def set_margin_type(symbol: str, margin_type: str = "ISOLATED") -> Any:
    return _CLIENT.set_margin_type(symbol, margin_type)

def set_leverage(symbol: str, leverage: int) -> Any:
    return _CLIENT.set_leverage(symbol, leverage)

# Order wrappers
def place_limit_order(
    symbol: str, side: str, quantity: float, price: float, *,
    post_only: bool = True, reduce_only: bool = False,
    position_side: Optional[str] = None, new_client_order_id: Optional[str] = None,
    time_in_force: Optional[str] = None,
) -> Dict[str, Any]:
    return _CLIENT.place_limit_order(
        symbol, side, quantity, price,
        post_only=post_only, reduce_only=reduce_only,
        position_side=position_side, new_client_order_id=new_client_order_id,
        time_in_force=time_in_force,
    )

def place_stop_limit(
    symbol: str, side: str, quantity: float, stop_price: float, limit_price: float, *,
    working_type: str = "MARK_PRICE", reduce_only: bool = False,
    position_side: Optional[str] = None, post_only: bool = True,
    price_protect: bool = True, new_client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _CLIENT.place_stop_limit(
        symbol, side, quantity, stop_price, limit_price,
        working_type=working_type, reduce_only=reduce_only,
        position_side=position_side, post_only=post_only,
        price_protect=price_protect, new_client_order_id=new_client_order_id,
    )

def place_stop_market(
    symbol: str, side: str, quantity: float, stop_price: float, *,
    working_type: str = "MARK_PRICE", reduce_only: bool = False,
    position_side: Optional[str] = None, price_protect: bool = True,
    new_client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _CLIENT.place_stop_market(
        symbol, side, quantity, stop_price,
        working_type=working_type, reduce_only=reduce_only,
        position_side=position_side, price_protect=price_protect,
        new_client_order_id=new_client_order_id,
    )

def cancel_order(symbol: str, order_id: Optional[int] = None, client_oid: Optional[str] = None) -> Dict[str, Any]:
    return _CLIENT.cancel_order(symbol, order_id, client_oid)

def cancel_all(symbol: str) -> Dict[str, Any]:
    return _CLIENT.cancel_all(symbol)

def get_order(symbol: str, order_id: Optional[int] = None, client_oid: Optional[str] = None) -> Dict[str, Any]:
    return _CLIENT.get_order(symbol, order_id, client_oid)


# =========== Self-checks ===========
if __name__ == "__main__":
    print("Ping:", fapi_ping())
    try:
        print("Server time:", _CLIENT.server_time())
    except Exception as e:
        print("Server time error:", e)

    try:
        bal = futures_balance()
        print("Balance sample:", bal[:1])
    except Exception as e:
        print("Balance error:", e)

















































































































































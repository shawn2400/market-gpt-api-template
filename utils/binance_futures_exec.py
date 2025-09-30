from __future__ import annotations
import os, time, hmac, hashlib
from typing import Dict, Any, Optional
import httpx
from urllib.parse import urlencode

BINANCE_FAPI_BASE = os.getenv("BINANCE_FAPI_BASE", "https://fapi.binance.com")
API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

class BinanceFuturesExec:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = (api_key or API_KEY).strip()
        self.api_secret = (api_secret or API_SECRET).strip().encode("utf-8")
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Binance API credentials not configured (BINANCE_API_KEY / BINANCE_API_SECRET)")
        self.base = BINANCE_FAPI_BASE.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {"X-MBX-APIKEY": self.api_key}

    def _sign(self, params: Dict[str, Any]) -> str:
        query = urlencode(params, doseq=True)
        signature = hmac.new(self.api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{query}&signature={signature}"

    def _ts(self) -> int:
        return int(time.time() * 1000)

    def post(self, path: str, params: Dict[str, Any], signed: bool = True) -> Any:
        url = f"{self.base}{path}"
        params = dict(params or {})
        if signed:
            params["timestamp"] = self._ts()
            params.setdefault("recvWindow", 5000)
            body = self._sign(params)
            data = body
            headers = self._headers()
        else:
            data = urlencode(params, doseq=True)
            headers = self._headers()
        with httpx.Client(timeout=15.0) as cli:
            r = cli.post(url, content=data, headers=headers)
            r.raise_for_status()
            return r.json()

    def get(self, path: str, params: Dict[str, Any], signed: bool = False) -> Any:
        url = f"{self.base}{path}"
        if signed:
            params = dict(params or {})
            params["timestamp"] = self._ts()
            params.setdefault("recvWindow", 5000)
            q = self._sign(params)
        else:
            q = urlencode(params or {}, doseq=True)
        with httpx.Client(timeout=15.0) as cli:
            r = cli.get(f"{url}?{q}", headers=self._headers())
            r.raise_for_status()
            return r.json()

    # ---- Helpers ----
    def set_leverage(self, symbol: str, leverage: int) -> Any:
        leverage = max(1, min(int(leverage), 125))
        return self.post("/fapi/v1/leverage", {"symbol": symbol.upper(), "leverage": leverage})

    def set_position_side_dual(self, dual_side: bool = False) -> Any:
        """
        dualSidePosition=true  => Hedge (Dual Side)
        dualSidePosition=false => One-way (BOTH)
        """
        return self.post("/fapi/v1/positionSide/dual", {"dualSidePosition": "true" if dual_side else "false"})

    def order_market(self, symbol: str, side: str, quantity: float,
                     position_side: str = "BOTH", reduce_only: bool = False) -> Any:
        """
        הזמנת MARKET. 'positionSide' יישלח רק אם LONG/SHORT כדי להימנע מהתנגשויות במצב One-way.
        """
        payload: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "MARKET",
            "quantity": f"{float(quantity):.6f}",
            "newOrderRespType": "RESULT",
        }
        ps = (position_side or "").upper()
        if ps in ("LONG", "SHORT"):
            payload["positionSide"] = ps
        if reduce_only:
            payload["reduceOnly"] = "true"
        return self.post("/fapi/v1/order", payload)

    def order_tp_or_sl_market(self, symbol: str, side: str, stop_price: float, quantity: float,
                              kind: str = "TAKE_PROFIT_MARKET",
                              position_side: str = "BOTH",
                              reduce_only: bool = True) -> Any:
        """
        kind ∈ {"TAKE_PROFIT_MARKET","STOP_MARKET"}
        הצד 'side' הוא צד הסגירה (הפוך לכניסה). שולחים positionSide רק אם LONG/SHORT.
        """
        assert kind in ("TAKE_PROFIT_MARKET", "STOP_MARKET")
        payload: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": kind,
            "stopPrice": f"{float(stop_price):.8f}",
            "workingType": "MARK_PRICE",
            "timeInForce": "GTC",
            "quantity": f"{float(quantity):.6f}",
            "newOrderRespType": "RESULT",
        }
        if reduce_only:
            payload["reduceOnly"] = "true"
        ps = (position_side or "").upper()
        if ps in ("LONG", "SHORT"):
            payload["positionSide"] = ps
        return self.post("/fapi/v1/order", payload)


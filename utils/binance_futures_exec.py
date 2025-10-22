# utils/binance_futures_exec.py
from __future__ import annotations
import os, time, hmac, hashlib
from typing import Dict, Any, Optional, List
import httpx
from urllib.parse import urlencode

BINANCE_FAPI_BASE = os.getenv("BINANCE_FAPI_BASE", os.getenv("BINANCE_FAPI", "https://fapi.binance.com"))
API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

class BinanceFuturesExec:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = (api_key or API_KEY).strip()
        self.api_secret = (api_secret or API_SECRET).strip().encode("utf-8")
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Binance API credentials not configured (BINANCE_API_KEY / BINANCE_API_SECRET)")
        self.base = (BINANCE_FAPI_BASE or "https://fapi.binance.com").rstrip("/")

    # ---------- low-level ----------
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
        else:
            data = urlencode(params, doseq=True)
        with httpx.Client(timeout=15.0) as cli:
            r = cli.post(url, content=data, headers=self._headers())
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

    def delete(self, path: str, params: Dict[str, Any], signed: bool = True) -> Any:
        url = f"{self.base}{path}"
        if signed:
            params = dict(params or {})
            params["timestamp"] = self._ts()
            params.setdefault("recvWindow", 5000)
            q = self._sign(params)
        else:
            q = urlencode(params or {}, doseq=True)
        with httpx.Client(timeout=15.0) as cli:
            r = cli.delete(f"{url}?{q}", headers=self._headers())
            r.raise_for_status()
            try:
                return r.json()
            except Exception:
                return {"status": r.status_code, "text": r.text}

    # ---------- Helpers / public endpoints ----------
    def get_exchange_filters(self, symbol: str) -> Dict[str, Any]:
        data = self.get("/fapi/v1/exchangeInfo", {"symbol": symbol.upper()}, signed=False)
        sym = (data.get("symbols") or [{}])[0]
        filters = sym.get("filters", [])
        out: Dict[str, Any] = {}
        for f in filters:
            ft = f.get("filterType")
            if ft == "PRICE_FILTER":
                out["tickSize"] = float(f.get("tickSize", 0))
            elif ft == "LOT_SIZE":
                out["stepSize"] = float(f.get("stepSize", 0))
                out["minQty"] = float(f.get("minQty", 0))
            elif ft in ("MIN_NOTIONAL", "MARKET_LOT_SIZE"):
                # ב־USDT-M futures השם לרוב "notional"
                n = f.get("notional") or f.get("minNotional")
                if n is not None:
                    out["minNotional"] = float(n)
        return out

    def get_mark_price(self, symbol: str) -> float:
        data = self.get("/fapi/v1/premiumIndex", {"symbol": symbol.upper()}, signed=False)
        return float(data.get("markPrice", 0.0))

    # ---------- Account / positions ----------
    def get_positions(self) -> List[Dict[str, Any]]:
        data = self.get("/fapi/v2/positionRisk", {}, signed=True)
        # מחזיר כבר רשימת פוזיציות; נשמור מבנה קריא:
        out: List[Dict[str, Any]] = []
        for p in data or []:
            out.append({
                "symbol": p.get("symbol"),
                "positionAmt": p.get("positionAmt"),
                "entryPrice": p.get("entryPrice"),
                "leverage": p.get("leverage"),
                "unrealizedProfit": p.get("unRealizedProfit") or p.get("unrealizedProfit"),
                "isolated": (str(p.get("isolated","false")).lower()=="true"),
                "markPrice": p.get("markPrice"),
            })
        return out

    def get_position(self, symbol: str) -> Dict[str, Any]:
        sym = symbol.upper()
        for p in self.get_positions():
            if (p.get("symbol") or "").upper() == sym:
                return p
        return {}

    def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        return self.get("/fapi/v1/openOrders", {"symbol": symbol.upper()}, signed=True)

    def cancel_order(self, symbol: str, order_id: int | str) -> Any:
        return self.delete("/fapi/v1/order", {"symbol": symbol.upper(), "orderId": order_id}, signed=True)

    def cancel_all_open_orders(self, symbol: str) -> Any:
        return self.delete("/fapi/v1/allOpenOrders", {"symbol": symbol.upper()}, signed=True)

    # ---------- Trading shortcuts ----------
    def set_leverage(self, symbol: str, leverage: int) -> Any:
        leverage = max(1, min(int(leverage), 125))
        return self.post("/fapi/v1/leverage", {"symbol": symbol.upper(), "leverage": leverage})

    def set_position_side_dual(self, dual_side: bool = False) -> Any:
        """dualSidePosition=true => Hedge; false => One-way."""
        return self.post("/fapi/v1/positionSide/dual", {"dualSidePosition": "true" if dual_side else "false"})

    def order_market(self, symbol: str, side: str, quantity: float,
                     position_side: str = "BOTH", reduce_only: bool = False) -> Any:
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
                              reduce_only: bool = True,
                              working_type: str = "MARK_PRICE") -> Any:
        """
        kind ∈ {"TAKE_PROFIT_MARKET","STOP_MARKET"}
        side — צד הסגירה (הפוך לכניסה).
        """
        assert kind in ("TAKE_PROFIT_MARKET", "STOP_MARKET")
        payload: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": kind,
            "stopPrice": f"{float(stop_price):.8f}",
            "workingType": working_type,
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


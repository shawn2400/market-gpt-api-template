# utils/account_clients.py
from __future__ import annotations
import httpx, hmac, time, logging
from hashlib import sha256
from typing import Any, Dict, Optional
from utils.account_router import get_account_credentials

logger = logging.getLogger("algogpt.account_clients")

def _sign(secret: str, qs: str) -> str:
    return hmac.new(secret.encode(), qs.encode(), sha256).hexdigest()

class BinanceAccountClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str):
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.base_url = base_url.rstrip("/")
        self.session = httpx.Client(
            timeout=httpx.Timeout(8.0),
            headers={"X-MBX-APIKEY": self.api_key, "Accept": "application/json"}
        )

    def _ts_ms(self) -> int:
        return int(time.time() * 1000)

    def request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None, signed: bool = False):
        url = f"{self.base_url}{path}"
        req_params = dict(params or {})
        if signed:
            req_params["timestamp"] = self._ts_ms()
            req_params["recvWindow"] = 45000
            query = "&".join([f"{k}={req_params[k]}" for k in req_params])
            req_params["signature"] = _sign(self.api_secret, query)
        return self.session.request(method.upper(), url, params=req_params)

# Cache ל־Clients
_clients: Dict[str, BinanceAccountClient] = {}

def get_account_client(account_id: str, market: str = "futures") -> Optional[BinanceAccountClient]:
    key = f"{account_id}:{market}"
    if key in _clients:
        return _clients[key]

    creds = get_account_credentials(account_id)
    if not creds:
        logger.error(f"Account {account_id} not found")
        return None

    api_key, api_secret = creds["api_key"], creds["api_secret"]
    if market == "spot":
        base = "https://api.binance.com"
    else:
        base = "https://fapi.binance.com"

    cli = BinanceAccountClient(api_key, api_secret, base)
    _clients[key] = cli
    return cli

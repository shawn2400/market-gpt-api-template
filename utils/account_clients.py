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
    """
    Client מבודד לחשבון אחד (Spot/Futures) עם ניהול חתימה ובקרת Timeout.
    """
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

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False
    ):
        url = f"{self.base_url}{path}"
        req_params = dict(params or {})

        if signed:
            req_params["timestamp"] = self._ts_ms()
            req_params["recvWindow"] = 45000
            # Binance דורש מיון פרמטרים לפי key
            query = "&".join([f"{k}={req_params[k]}" for k in sorted(req_params.keys())])
            req_params["signature"] = _sign(self.api_secret, query)

        try:
            resp = self.session.request(method.upper(), url, params=req_params)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"[{method}] {url} failed: {e}")
            return {"error": str(e)}

# Cache ל־Clients (Spot/Futures לכל חשבון)
_clients: Dict[str, BinanceAccountClient] = {}

def get_account_client(account_id: str, market: str = "futures") -> Optional[BinanceAccountClient]:
    """
    מחזיר client מוכן לחשבון ספציפי.
    account_id חייב להתאים לערך בקובץ accounts_config.json
    """
    key = f"{account_id}:{market}"
    if key in _clients:
        return _clients[key]

    creds = get_account_credentials(account_id)
    if not creds:
        logger.error(f"❌ Account {account_id} not found in accounts_config.json")
        return None

    api_key, api_secret = creds.get("api_key"), creds.get("api_secret")
    if not api_key or not api_secret:
        logger.error(f"❌ Missing API keys for account {account_id}")
        return None

    base = "https://api.binance.com" if market == "spot" else "https://fapi.binance.com"
    cli = BinanceAccountClient(api_key, api_secret, base)
    _clients[key] = cli
    return cli


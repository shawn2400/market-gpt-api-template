# utils/binance_spot_client.py
from __future__ import annotations
import logging
from binance.client import Client
from typing import Optional, Dict

logger = logging.getLogger("algogpt.binance_spot_client")

# Cache clients כדי שלא נבנה כל קריאה מחדש
_spot_clients: Dict[str, Client] = {}

def get_spot_client(api_key: str, api_secret: str, account_id: str = "main") -> Client:
    """
    יוצר או מחזיר Binance Spot Client לפי account_id.
    """
    if account_id in _spot_clients:
        return _spot_clients[account_id]

    client = Client(api_key, api_secret)
    client.API_URL = "https://api.binance.com"  # Spot endpoint
    _spot_clients[account_id] = client
    logger.info(f"[SpotClient] ✅ Client initialized for account_id={account_id}")
    return client


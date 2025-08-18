# utils/onchain.py
from __future__ import annotations
import os
import time
from typing import Dict, Any, List

import requests

__all__ = [
    "fetch_btc_onchain",
    "fetch_eth_onchain",
    "get_onchain_overview",
]

HTTP_TIMEOUT = float(os.getenv("ONCHAIN_TIMEOUT_SEC", "8.0"))
CACHE_TTL = float(os.getenv("ONCHAIN_CACHE_TTL_SEC", "60.0"))

_s = requests.Session()
_s.trust_env = False
_s.headers.update({
    "User-Agent": "AlgoGPT/2 onchain",
    "Accept": "application/json",
})

_cache: Dict[str, Dict[str, Any]] = {}


def _get(url: str, params: Dict[str, Any] | None = None, timeout: float = HTTP_TIMEOUT):
    r = _s.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_btc_onchain() -> Dict[str, Any]:
    """
    מקורות:
      - mempool.space: עמלות מומלצות
      - blockchair: סטטיסטיקות Bitcoin
    """
    now = time.monotonic()
    ent = _cache.get("BTC")
    if ent and (now - ent["t"] <= CACHE_TTL):
        return dict(ent["data"])

    out: Dict[str, Any] = {"ok": True, "chain": "BTC"}
    try:
        fees = _get("https://mempool.space/api/v1/fees/recommended")
        out["fees"] = {
            "fastestFee_satvkB": fees.get("fastestFee"),
            "halfHourFee_satvkB": fees.get("halfHourFee"),
            "hourFee_satvkB": fees.get("hourFee"),
            "economyFee_satvkB": fees.get("economyFee"),
            "minimumFee_satvkB": fees.get("minimumFee"),
        }
    except Exception as e:
        out.setdefault("warnings", []).append(f"fees: {e}")

    try:
        bc = _get("https://api.blockchair.com/bitcoin/stats")
        data = (bc or {}).get("data") or {}
        out["stats"] = {
            "blocks": data.get("blocks"),
            "best_block_height": data.get("best_block_height"),
            "transactions_24h": data.get("transactions_24h"),
            "hashrate_24h_ths": data.get("hashrate_24h"),  # TH/s
            "difficulty": data.get("difficulty"),
            "mempool_transactions": data.get("mempool_transactions"),
            "circulation": data.get("circulation"),
        }
    except Exception as e:
        out.setdefault("warnings", []).append(f"blockchair: {e}")

    _cache["BTC"] = {"t": now, "data": out}
    return dict(out)


def fetch_eth_onchain() -> Dict[str, Any]:
    """
    מקורות:
      - blockchair: סטטיסטיקות Ethereum (כולל gas_price_wei)
    """
    now = time.monotonic()
    ent = _cache.get("ETH")
    if ent and (now - ent["t"] <= CACHE_TTL):
        return dict(ent["data"])

    out: Dict[str, Any] = {"ok": True, "chain": "ETH"}
    try:
        bc = _get("https://api.blockchair.com/ethereum/stats")
        data = (bc or {}).get("data") or {}
        gas_wei = data.get("gas_price_wei")
        out["stats"] = {
            "best_block_height": data.get("best_block_height"),
            "transactions_24h": data.get("transactions_24h"),
            "gas_price_wei": gas_wei,
            "gas_price_gwei": (float(gas_wei) / 1e9) if isinstance(gas_wei, (int, float)) else None,
            "mempool_transactions": data.get("mempool_transactions"),
            "circulation_wei": data.get("circulation"),
        }
    except Exception as e:
        out.setdefault("warnings", []).append(f"blockchair: {e}")

    _cache["ETH"] = {"t": now, "data": out}
    return dict(out)


def get_onchain_overview(targets: List[str] | None = None) -> Dict[str, Any]:
    """
    Aggregation נוח ל־Dashboard/AI:
      targets: ["BTC","ETH"] (ברירת מחדל)
    """
    targets = targets or ["BTC", "ETH"]
    out: Dict[str, Any] = {"ok": True, "chains": {}}
    for t in targets:
        t = t.upper()
        try:
            if t == "BTC":
                out["chains"]["BTC"] = fetch_btc_onchain()
            elif t == "ETH":
                out["chains"]["ETH"] = fetch_eth_onchain()
            else:
                out["chains"][t] = {"ok": False, "error": "unsupported"}
        except Exception as e:
            out["chains"][t] = {"ok": False, "error": str(e)}
    return out


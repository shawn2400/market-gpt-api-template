# utils/onchain.py
from __future__ import annotations
import time
from typing import Dict, Any, List
import requests

_S = requests.Session()
_S.trust_env = False
_S.headers.update({"User-Agent": "AlgoGPT/2 onchain", "Accept": "application/json"})

def _get(url: str, timeout: float = 6.5):
    r = _S.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _btc_sources() -> Dict[str, Any]:
    warnings: List[str] = []
    fees = None
    stats = None
    try:
        # mempool.space recommended fees
        fees = _get("https://mempool.space/api/v1/fees/recommended")
    except Exception as e:
        warnings.append(f"fees: {e}")
    try:
        # blockchair stats
        stats = _get("https://api.blockchair.com/bitcoin/stats").get("data", {})
    except Exception as e:
        warnings.append(f"stats: {e}")
    return {"ok": True, "chain": "BTC", "fees": fees, "stats": stats, "warnings": warnings or None}

def _eth_sources() -> Dict[str, Any]:
    warnings: List[str] = []
    fees = None
    stats = None
    try:
        # Ethereum gas (blockchair has gas_price, suggested EIP-1559 base fee info)
        stats_all = _get("https://api.blockchair.com/ethereum/stats")
        stats = stats_all.get("data", {})
        fees = {
            "gas_price_wei": stats.get("gas_price"),
            "gas_price_gwei": (stats.get("gas_price") or 0) / 1e9 if stats.get("gas_price") else None,
            "pending_tx": stats.get("mempool_transactions"),
        }
    except Exception as e:
        warnings.append(f"stats/fees: {e}")
    return {"ok": True, "chain": "ETH", "fees": fees, "stats": stats, "warnings": warnings or None}

def get_onchain_overview(targets: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for t in targets:
        t = t.upper()
        if t == "BTC":
            out["BTC"] = _btc_sources()
        elif t == "ETH":
            out["ETH"] = _eth_sources()
        else:
            out[t] = {"ok": False, "chain": t, "fees": None, "stats": None, "warnings": [f"unsupported chain: {t}"]}
    return {"ok": True, "chains": out, "ts": int(time.time())}




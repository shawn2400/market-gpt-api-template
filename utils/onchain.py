# utils/onchain.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
import time
import requests

_S = requests.Session()
_S.trust_env = False
_S.headers.update({
    "User-Agent": "AlgoGPT/2 onchain",
    "Accept": "application/json",
})

def _get_json(url: str, timeout: float = 6.0) -> Optional[dict]:
    try:
        r = _S.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(0.5)
            r2 = _S.get(url, timeout=timeout)
            if r2.status_code == 200:
                return r2.json()
    except Exception:
        pass
    return None

# ---------- BTC (mempool.space) ----------
def _btc_fees() -> Optional[Dict[str, Any]]:
    j = _get_json("https://mempool.space/api/v1/fees/recommended")
    if not j:
        return None
    return {
        "fastestFee": j.get("fastestFee"),
        "halfHourFee": j.get("halfHourFee"),
        "hourFee": j.get("hourFee"),
        "economyFee": j.get("economyFee"),
        "minimumFee": j.get("minimumFee"),
        "unit": "sat/vB",
    }

def _btc_stats() -> Dict[str, Any]:
    h = None
    try:
        r = _S.get("https://mempool.space/api/blocks/tip/height", timeout=5)
        if r.status_code == 200:
            h = int(r.text.strip())
    except Exception:
        pass
    mem = _get_json("https://mempool.space/api/mempool") or {}
    return {
        "height": h,
        "mempool": {
            "tx_count": mem.get("count"),
            "vsize": mem.get("vsize"),
            "total_fee_sat": mem.get("total_fee"),
        },
    }

def _btc_overview() -> Dict[str, Any]:
    fees = _btc_fees()
    stats = _btc_stats()
    warnings = []
    if fees is None:
        warnings.append("fees_unavailable")
    if not stats.get("height"):
        warnings.append("height_unavailable")
    return {"ok": True, "fees": fees, "stats": stats, "warnings": warnings or None}

# ---------- ETH ----------
def _eth_gas_oracle() -> Optional[Dict[str, Any]]:
    j = _get_json("https://www.etherchain.org/api/gasPriceOracle")
    if not j:
        return None
    return {
        "safeLow": j.get("safeLow"),
        "standard": j.get("standard"),
        "fast": j.get("fast"),
        "fastest": j.get("fastest"),
        "unit": "gwei",
    }

def _eth_stats_blockchair() -> Optional[Dict[str, Any]]:
    j = _get_json("https://api.blockchair.com/ethereum/stats")
    if not j or "data" not in j:
        return None
    d = j["data"]
    return {
        "blocks": d.get("blocks"),
        "transactions_24h": d.get("transactions_24h"),
        "mempool_transactions": d.get("mempool_transactions"),
        "hashrate": d.get("hashrate_24h"),
        "difficulty": d.get("difficulty"),
    }

def _eth_overview() -> Dict[str, Any]:
    fees = _eth_gas_oracle()
    stats = _eth_stats_blockchair() or {}
    warnings = []
    if fees is None:
        warnings.append("gas_oracle_unavailable")
    if not stats:
        warnings.append("stats_unavailable")
    return {"ok": True, "fees": fees, "stats": stats or None, "warnings": warnings or None}

# ---------- Public API ----------
def overview(chains: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for c in chains:
        up = str(c or "").upper()
        if up == "BTC":
            out[up] = _btc_overview()
        elif up == "ETH":
            out[up] = _eth_overview()
        else:
            out[up] = {"ok": False, "fees": None, "stats": None, "warnings": ["unsupported_chain"]}
    return {"ok": True, "chains": out}






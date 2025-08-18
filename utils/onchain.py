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
        # נסיון מהיר נוסף לשגיאות זמניות
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
    # https://mempool.space/api/v1/fees/recommended
    j = _get_json("https://mempool.space/api/v1/fees/recommended")
    if not j:
        return None
    # מחזיר ביחידות sat/vB
    return {
        "fastestFee": j.get("fastestFee"),
        "halfHourFee": j.get("halfHourFee"),
        "hourFee": j.get("hourFee"),
        "economyFee": j.get("economyFee"),
        "minimumFee": j.get("minimumFee"),
        "unit": "sat/vB",
    }

def _btc_stats() -> Dict[str, Any]:
    # height
    h = None
    try:
        # https://mempool.space/api/blocks/tip/height  מחזיר מספר גולמי
        r = _S.get("https://mempool.space/api/blocks/tip/height", timeout=5)
        if r.status_code == 200:
            h = int(r.text.strip())
    except Exception:
        pass

    # mempool summary
    mem = _get_json("https://mempool.space/api/mempool") or {}
    # mem => {count, vsize, total_fee}
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
    warnings: List[str] = []
    if fees is None:
        warnings.append("fees_unavailable")
    if not stats.get("height"):
        warnings.append("height_unavailable")
    return {"ok": True, "fees": fees, "stats": stats, "warnings": warnings or None}

# ---------- ETH (etherchain.org + (אופציונלי) Blockchair) ----------
def _eth_gas_oracle() -> Optional[Dict[str, Any]]:
    # https://www.etherchain.org/api/gasPriceOracle  (ללא מפתח)
    j = _get_json("https://www.etherchain.org/api/gasPriceOracle")
    if not j:
        return None
    # שדות לדוגמה: { "safeLow": 7.7, "standard": 8.2, "fast": 8.9, "fastest": 10.5 }
    return {
        "safeLow": j.get("safeLow"),
        "standard": j.get("standard"),
        "fast": j.get("fast"),
        "fastest": j.get("fastest"),
        "unit": "gwei",
    }

def _eth_stats_blockchair() -> Optional[Dict[str, Any]]:
    # public – עלול להיות rate-limited, לכן אופציונלי
    j = _get_json("https://api.blockchair.com/ethereum/stats")
    if not j or "data" not in j:
        return None
    data = j["data"]
    # תת-קבוצה שימושית; אפשר להרחיב לפי הצורך
    out = {
        "blocks": data.get("blocks"),
        "transactions_24h": data.get("transactions_24h"),
        "mempool_transactions": data.get("mempool_transactions"),
        "hashrate": data.get("hashrate_24h"),  # H/s
        "difficulty": data.get("difficulty"),
    }
    return out

def _eth_overview() -> Dict[str, Any]:
    fees = _eth_gas_oracle()
    stats = _eth_stats_blockchair() or {}
    warnings: List[str] = []
    if fees is None:
        warnings.append("gas_oracle_unavailable")
    if not stats:
        warnings.append("stats_unavailable")
    return {"ok": True, "fees": fees, "stats": stats or None, "warnings": warnings or None}

# ---------- Public API ----------
def overview(chains: List[str]) -> Dict[str, Any]:
    """
    מחזיר מבט־על On-Chain לפי רשימת שרשראות (למשל ['BTC','ETH']).
    לא נכשל אם ספק לא זמין — מחזיר אזהרות.
    """
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





# utils/onchain_risk.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os, time, json, asyncio
from typing import Dict, Optional, Tuple, List
import httpx

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

"""
🔹 ייעוד: איתור "on-chain anomalies" לשימוש כסיגנל סיכון/חדשות (לא טריגר מסחר).
- Bitquery (GraphQL): large transfers / whale inflow/outflow (CEX)
- Etherscan: בדיקות קלות (לינק/מטא/בדיקות נקודתיות)
- The Graph (אופציונלי): אינדוקס פרוטוקולים/TVL/Volumes – ניתן להרחיב בהמשך
Cache: Redis או in-memory TTL
Fail-open: מחזיר score=0 אם ספק לא זמין
ENV:
  ONCHAIN_ENABLE=1
  ONCHAIN_PROVIDER=bitquery
  ONCHAIN_TIMEOUT_MS=2000
  ONCHAIN_CACHE_TTL_SEC=900
  BITQUERY_API_KEY=...
  ETHERSCAN_ENABLE=1
  ETHERSCAN_API_KEY=...
  RISK_GATE_ONCHAIN_COOLDOWN_MIN=30
"""

ONCHAIN_ENABLE = (os.getenv("ONCHAIN_ENABLE", "1").lower() in ("1", "true", "yes", "on"))
PROVIDER = (os.getenv("ONCHAIN_PROVIDER", "bitquery").strip().lower() or "bitquery")
TIMEOUT = float(int(os.getenv("ONCHAIN_TIMEOUT_MS", "2000")) / 1000.0)
TTL = int(os.getenv("ONCHAIN_CACHE_TTL_SEC", "900") or "900")
COOLDOWN_MIN = int(os.getenv("RISK_GATE_ONCHAIN_COOLDOWN_MIN", "30") or "30")

BITQUERY_API_KEY = os.getenv("BITQUERY_API_KEY", "")
ETHERSCAN_ENABLE = (os.getenv("ETHERSCAN_ENABLE", "1").lower() in ("1", "true", "yes", "on"))
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")

_mem: Dict[str, Tuple[float, Dict]] = {}
_http_client: Optional[httpx.AsyncClient] = None
_http_lock = asyncio.Lock()
_redis = None
_redis_lock = asyncio.Lock()

async def get_http_client() -> httpx.AsyncClient:
    global _http_client
    async with _http_lock:
        if _http_client is None or _http_client.is_closed:
            _http_client = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT, connect=1.0),
                                             headers={"User-Agent": "AlgoGPT-OnChain/1.0"})
    return _http_client

async def get_redis():
    global _redis
    if aioredis is None:
        return None
    if _redis is not None:
        return _redis
    url = os.getenv("REDIS_URL") or ""
    if not url:
        return None
    async with _redis_lock:
        if _redis is None:
            _redis = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
    return _redis

def _mem_get(key: str) -> Optional[Dict]:
    item = _mem.get(key)
    if not item:
        return None
    ts, obj = item
    if (time.time() - ts) > TTL:
        _mem.pop(key, None)
        return None
    return obj

def _mem_set(key: str, obj: Dict) -> None:
    _mem[key] = (time.time(), obj)

async def _redis_get(key: str) -> Optional[Dict]:
    r = await get_redis()
    if not r:
        return None
    raw = await r.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None

async def _redis_set(key: str, obj: Dict, ttl: int) -> None:
    r = await get_redis()
    if not r:
        return
    try:
        await r.set(key, json.dumps(obj), ex=ttl)
    except Exception:
        pass

# ---------------- Bitquery (GraphQL) ----------------
BITQUERY_URL = "https://graphql.bitquery.io"

BITQUERY_QUERY_LARGE_TRANSFERS = """
query($network: EthereumNetwork!, $address: String!, $usdMin: Float!, $since: ISO8601DateTime!) {
  ethereum(network: $network) {
    transfers(
      date: {since: $since}
      amountUsd: {gt: $usdMin}
      any: [{receiver: {is: $address}}, {sender: {is: $address}}]
    ) {
      amountUsd
      currency { symbol address }
      sender { address annotation }
      receiver { address annotation }
      external
    }
  }
}
"""

async def _bitquery_large_transfers(network: str, address: str, usd_min: float, minutes_back: int) -> List[Dict]:
    if not BITQUERY_API_KEY:
        return []
    vars_ = {
        "network": network,
        "address": address,
        "usdMin": float(usd_min),
        "since": f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time()-minutes_back*60))}",
    }
    try:
        cli = await get_http_client()
        r = await cli.post(BITQUERY_URL, json={"query": BITQUERY_QUERY_LARGE_TRANSFERS, "variables": vars_},
                           headers={"X-API-KEY": BITQUERY_API_KEY})
        r.raise_for_status()
        data = r.json() or {}
        transfers = (((data.get("data") or {}).get("ethereum") or {}).get("transfers") or [])
        return transfers
    except Exception:
        return []

# ---------------- Etherscan helpers ----------------
async def etherscan_tx_count(addr: str, network: str = "mainnet") -> Optional[int]:
    """דוגמה לבדיקת מטא קלה – לא כבדת עלויות."""
    if not ETHERSCAN_ENABLE or not ETHERSCAN_API_KEY:
        return None
    base = "https://api.etherscan.io/api"
    # (במידת הצורך רשתות ליבה נוספות: api-goerli, api-optimistic וכו’)
    try:
        cli = await get_http_client()
        r = await cli.get(base, params={"module": "proxy", "action": "eth_getTransactionCount",
                                        "address": addr, "tag": "latest", "apikey": ETHERSCAN_API_KEY})
        r.raise_for_status()
        js = r.json() or {}
        result = js.get("result")
        if isinstance(result, str) and result.startswith("0x"):
            return int(result, 16)
    except Exception:
        return None
    return None

# ---------------- Public API ----------------
async def analyze_asset(network: str, address: str, symbol: str,
                        large_usd_min: float = 500_000.0,
                        lookback_min: int = 30) -> Dict:
    """
    מחזיר אובייקט סיכון קריא:
    {
      "symbol": "USDT",
      "network": "ethereum",
      "address": "0x...",
      "score": 0..100,
      "signals": [{"type": "...", "detail": "...", "weight": int}, ...],
      "cooldown_min": 30
    }
    *score* ניתן למיפוי ישיר ל-News/Risk Gate (למשל score>=50 → הקפאה 15–45 דק’).
    """
    out = {"symbol": symbol, "network": network, "address": address, "score": 0, "signals": [], "cooldown_min": COOLDOWN_MIN}
    if not ONCHAIN_ENABLE:
        return out

    key = f"onchain:{network}:{address}:{large_usd_min}:{lookback_min}"
    cached = await _redis_get(key)
    if not cached:
        cached = _mem_get(key)
    if cached:
        return cached

    score = 0
    signals: List[Dict] = []

    # Bitquery – large transfers (whale inflow/outflow)
    if PROVIDER == "bitquery" and BITQUERY_API_KEY:
        transfers = await _bitquery_large_transfers(network=network, address=address, usd_min=large_usd_min, minutes_back=lookback_min)
        if transfers:
            # משקל שמרני – לא להדליק “אש אדומה” בקלות
            weight = min(60, 10 + len(transfers) * 5)
            score += weight
            signals.append({"type": "whale_flow", "detail": f"{len(transfers)} large transfers ≥ ${int(large_usd_min):,} in {lookback_min}m", "weight": weight})

    # Etherscan – בדיקת מטא קלה (אופציונלי)
    txc = await etherscan_tx_count(address) if ETHERSCAN_ENABLE and ETHERSCAN_API_KEY else None
    if txc is not None:
        # אין משקל גדול – סמן מידע בלבד
        signals.append({"type": "etherscan_meta", "detail": f"tx_count={txc}", "weight": 0})

    out.update({"score": min(score, 100), "signals": signals})

    _mem_set(key, out)
    await _redis_set(key, out, TTL)
    return out

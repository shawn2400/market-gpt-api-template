# utils/funding_bias.py
from __future__ import annotations
import os, time, json, asyncio
from typing import Dict, Any, Optional
import httpx

from utils.redis_client import redis_client as RED

BINANCE_FAPI = os.getenv("BINANCE_FAPI", "https://fapi.binance.com")

# Cache / Bias knobs
FUNDING_TTL_SEC     = int(float(os.getenv("FUNDING_TTL_SEC", "1800")))  # 30m cache
FUNDING_STRONG_PCT  = float(os.getenv("FUNDING_STRONG_PCT", "0.0003"))  # 0.03%
FUNDING_MAX_BIAS    = float(os.getenv("FUNDING_MAX_BIAS", "0.25"))      # עד ±25% השפעה לכל היותר
FUNDING_ENABLED     = os.getenv("FUNDING_ENABLED", "1").lower() in ("1","true","yes")

_KEY_FMT = "algogpt:funding:{sym}"

async def _fetch_premium_index(symbol: str) -> Optional[Dict[str, Any]]:
    """
    /fapi/v1/premiumIndex?symbol=BTCUSDT
    מחזיר lastFundingRate + Mark/Index + nextFundingTime.
    """
    url = f"{BINANCE_FAPI}/fapi/v1/premiumIndex"
    async with httpx.AsyncClient(timeout=7) as client:
        r = await client.get(url, params={"symbol": symbol.upper()})
        r.raise_for_status()
        return r.json()

def _now() -> int: return int(time.time())

def _cache_get(symbol: str) -> Optional[Dict[str, Any]]:
    if RED:
        raw = RED.get(_KEY_FMT.format(sym=symbol.upper()))
        if raw:
            try: return json.loads(raw)
            except Exception: return None
    return globals().get(_KEY_FMT.format(sym=symbol.upper()))

def _cache_put(symbol: str, obj: Dict[str, Any]) -> None:
    key = _KEY_FMT.format(sym=symbol.upper())
    if RED:
        RED.setex(key, FUNDING_TTL_SEC, json.dumps(obj, ensure_ascii=False))
    else:
        globals()[key] = obj

async def get_funding_rate(symbol: str) -> float:
    """
    מחזיר funding rate האחרון (מספר, לדוגמה 0.0001=0.01%).
    """
    if not FUNDING_ENABLED:
        return 0.0

    cached = _cache_get(symbol)
    if cached and (cached.get("exp", 0) > _now()):
        try:
            return float(cached.get("rate") or 0.0)
        except Exception:
            pass

    try:
        data = await _fetch_premium_index(symbol)
        rate = float(data.get("lastFundingRate") or 0.0)
    except Exception:
        # במקרה כשל — נשתמש במטמון קודם אם היה, אחרת 0
        rate = float((cached or {}).get("rate") or 0.0)

    _cache_put(symbol, {"rate": rate, "exp": _now() + FUNDING_TTL_SEC})
    return rate

def funding_bias_direction(rate: float) -> str:
    """
    rate>0 → לונגים משלמים, שוק מוטה LONG → הטיה קונטרה קלה לכיוון SHORT.
    rate<0 → שורטים משלמים → הטיה קונטרה קלה לכיוון LONG.
    rate≈0 → NEUTRAL.
    """
    if abs(rate) < (FUNDING_STRONG_PCT / 2.0):
        return "NEUTRAL"
    return "SHORT" if rate > 0 else "LONG"

def funding_bias_factor(rate: float, side: Optional[str] = None) -> float:
    """
    מחזיר פקטור ∈ [-FUNDING_MAX_BIAS, +FUNDING_MAX_BIAS] להטיה עדינה.
    חיובי → מחזק את הכיוון; שלילי → מחליש.
    אנו בוחרים *קונטרה* למצב השוק:
      - rate>0 (מוטה LONG) → penalize LONG / favor SHORT.
      - rate<0 (מוטה SHORT) → penalize SHORT / favor LONG.
    """
    if not FUNDING_ENABLED:
        return 0.0

    norm = min(1.0, abs(rate) / max(1e-12, FUNDING_STRONG_PCT))
    base = norm * FUNDING_MAX_BIAS   # 0..max

    if side is None:
        # כיוון כללי (לא ספציפי ל-side)
        return base if rate < 0 else -base

    s = side.upper()
    if rate > 0:
        # penalize LONG, favor SHORT
        return -base if s == "LONG" else +base
    if rate < 0:
        # penalize SHORT, favor LONG
        return +base if s == "LONG" else -base
    return 0.0

def adjust_success_pct(success_pct: float, rate: float, side: str) -> float:
    """
    התאמת success_pct עדינה לפי funding.
    """
    f = funding_bias_factor(rate, side)
    # נתרגם פקטור ±0.25 לכ-±4% בניצחון (לייט-טאץ')
    adj = 16.0 * f   # 0.25 → 4.0
    out = float(success_pct or 0.0) + adj
    return max(0.0, min(100.0, out))

async def funding_bias(symbol: str, side: Optional[str] = None) -> Dict[str, Any]:
    """
    עטיפה נוחה: מחזיר את כל הנתונים לשילוב בגייטינג.
    """
    rate = await get_funding_rate(symbol)
    direction = funding_bias_direction(rate)
    factor = funding_bias_factor(rate, side)
    return {
        "symbol": symbol.upper(),
        "rate": rate,
        "direction": direction,
        "factor": factor,
        "threshold": FUNDING_STRONG_PCT,
        "max_bias": FUNDING_MAX_BIAS,
        "enabled": FUNDING_ENABLED,
    }


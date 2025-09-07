# utils/safe.py
from __future__ import annotations
import time
from typing import Callable, Any, Dict
from binance.exceptions import BinanceAPIException, BinanceRequestException

_quarantine: Dict[str, float] = {}
_QUARANTINE_TTL = 300  # 5 דקות

def safe_ext(fn: Callable[[], Any]) -> Dict[str, Any]:
    try:
        return {"ok": True, "data": fn()}
    except (BinanceAPIException, BinanceRequestException) as e:
        msg = str(e); code = getattr(e,"code",None)
        if code == -1003 or "banned" in msg.lower():
            return {"ok": False, "http":503, "code":"BINANCE_IP_BANNED", "error":msg}
        return {"ok": False, "http":502, "code":"BINANCE_ERROR", "error":msg}
    except Exception as e:
        em = str(e)
        if "CloudFront" in em or ("403" in em and "HTML" in em):
            return {"ok": False,"http":503,"code":"WAF_BLOCK","error":em}
        return {"ok": False,"http":500,"code":"INTERNAL","error":em}

def mark_quarantine(symbol: str) -> None:
    _quarantine[symbol.upper()] = time.time() + _QUARANTINE_TTL

def is_quarantined(symbol: str) -> bool:
    exp = _quarantine.get(symbol.upper(), 0)
    return exp > time.time()


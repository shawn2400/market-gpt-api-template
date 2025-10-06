# utils/quantize.py
from __future__ import annotations
import math
from functools import lru_cache
from typing import Dict, Any

__all__ = ["get_filters", "quantize_price", "quantize_qty"]

@lru_cache(maxsize=512)
def _exchange_info_raw(api_key: str, api_sec: str) -> Dict[str, Any]:
    from binance.client import Client  # type: ignore
    cli = Client(api_key, api_sec)
    return cli.futures_exchange_info() or {}

@lru_cache(maxsize=2048)
def get_filters(client, symbol: str) -> Dict[str, float]:
    """
    מחלץ tickSize ו-stepSize עבור symbol (עם cache).
    """
    info = client.futures_exchange_info() or {}
    sym = symbol.upper()
    tick = 0.01
    step = 0.001
    for s in info.get("symbols", []):
        if s.get("symbol") == sym:
            for f in s.get("filters", []):
                if f.get("filterType") == "PRICE_FILTER":
                    tick = float(f.get("tickSize", tick))
                elif f.get("filterType") == "LOT_SIZE":
                    step = float(f.get("stepSize", step))
            break
    return {"tick": float(tick), "step": float(step)}

def _floor_to(x: float, step: float) -> float:
    return math.floor(float(x) / float(step)) * float(step)

def quantize_price(symbol: str, px: float, filters: Dict[str, float]) -> float:
    tick = float(filters.get("tick") or 0.01)
    return float(f"{_floor_to(float(px), tick):.12f}")

def quantize_qty(symbol: str, qty: float, filters: Dict[str, float]) -> float:
    step = float(filters.get("step") or 0.001)
    q = _floor_to(float(qty), step)
    # חיתוך רעשים בינאריים
    return float(f"{q:.12f}")


# utils/multi_tf_scanner.py
from typing import List, Dict, Any, Optional
from . import scanner_utils as su

async def fallback_scan_manual(symbol: str) -> List[Dict[str, Any]]:
    """
    סריקה ידנית עבור סימבול יחיד בטיימפריים 15m ו-1h.
    """
    out: List[Dict[str, Any]] = []
    for tf in ("15m", "1h"):
        x = await su.analyze_symbol(symbol, interval=tf, frames=[tf])
        if x:
            out.append(x)
    return out


























































































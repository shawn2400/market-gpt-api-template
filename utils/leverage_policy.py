# utils/leverage_policy.py
from __future__ import annotations
import os

# dynamic cap from runtime (degrade/bump)
try:
    from utils.runtime_counters import get_current_max_leverage
except Exception:
    def get_current_max_leverage(x:int)->int: return x

_MIN_LEV = int(os.getenv("MIN_LEVERAGE", "5"))
_MAX_LEV = int(os.getenv("MAX_LEVERAGE", "35"))

_ADX_MAX_SAFE = int(os.getenv("OPS_ADX_SAFETY_MAX_LEVERAGE", "15"))   # upper bound under strong trend
# buckets to ease: e.g. "20,25,30" → (<20, <25, <30, >=30)
_ADX_CUTOFFS = [int(x) for x in os.getenv("OPS_ADX_LEVERAGE_CUTOFFS","20,25,30").split(",") if x.strip().isdigit()][:3] or [20,25,30]

# light mapping for safety cap by ADX bucket
# <c0 → 9x,  <c1 → 12x,  <c2 → _ADX_MAX_SAFE,  else → _ADX_MAX_SAFE
_CAPS = [9, 12, _ADX_MAX_SAFE, _ADX_MAX_SAFE]

def _adx_safety_cap(adx: float) -> int:
    for i, c in enumerate(_ADX_CUTOFFS):
        if adx < c:
            return _CAPS[i]
    return _CAPS[-1]

def adjust_leverage(adx: float, proposed_leverage: int) -> int:
    """
    Enforce:
    1) hard env MIN/MAX
    2) dynamic degrade/bump cap (runtime)
    3) ADX safety cap (progressive)
    """
    hard_max = _MAX_LEV
    dyn_max  = get_current_max_leverage(hard_max)
    safe_max = _adx_safety_cap(float(adx))
    final = max(_MIN_LEV, min(int(proposed_leverage), hard_max, dyn_max, safe_max))
    return final



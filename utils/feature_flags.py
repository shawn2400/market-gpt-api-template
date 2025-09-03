# utils/feature_flags.py
from __future__ import annotations
import os, threading
from typing import Optional

# דגלים בזיכרון (Override בזמן ריצה)
_FLAGS: dict[str, bool] = {}
_LOCK = threading.Lock()

def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None: return default
    return str(v).strip().lower() in ("1","true","yes","on")

def get_flag(name: str, default: bool = False) -> bool:
    with _LOCK:
        if name in _FLAGS:
            return bool(_FLAGS[name])
    return _env_bool(name, default)

def set_flag(name: str, value: bool) -> None:
    with _LOCK:
        _FLAGS[name] = bool(value)

# שמות נוחים (ברירת־מחדל: כבוי)
FEAT_BTC_GATE          = "FEAT_BTC_GATE"
FEAT_TF_ALIGN          = "FEAT_TF_ALIGN"
FEAT_SPREAD_DEPTH      = "FEAT_SPREAD_DEPTH"
FEAT_MARK_INDEX_SANITY = "FEAT_MARK_INDEX_SANITY"
FEAT_VOLUME_GATE       = "FEAT_VOLUME_GATE"
FEAT_PUMP_NUKE         = "FEAT_PUMP_NUKE"
FEAT_QUALITY_ENFORCE   = "FEAT_QUALITY_ENFORCE"
FEAT_DAILY_CAPS        = "FEAT_DAILY_CAPS"
FEAT_COOLDOWN          = "FEAT_COOLDOWN"
FEAT_DEBOUNCE_LIMIT    = "FEAT_DEBOUNCE_LIMIT"

__all__ = ["get_flag","set_flag",
           "FEAT_BTC_GATE","FEAT_TF_ALIGN","FEAT_SPREAD_DEPTH","FEAT_MARK_INDEX_SANITY",
           "FEAT_VOLUME_GATE","FEAT_PUMP_NUKE","FEAT_QUALITY_ENFORCE","FEAT_DAILY_CAPS",
           "FEAT_COOLDOWN","FEAT_DEBOUNCE_LIMIT"]


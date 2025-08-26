# utils/time_windows.py
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

def hour_regime(tz: str = "Asia/Jerusalem") -> str:
    h = datetime.now(ZoneInfo(tz)).hour
    if h in [16,17,18,19,20,21,22,23,0,1]:
        return "hot"
    if h in [4,5,6,7,8,9]:
        return "calm"
    return "mid"

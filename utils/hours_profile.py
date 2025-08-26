# utils/hours_profile.py
from __future__ import annotations
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# ENV דוגמא:
# HOT_HOURS="09:00-12:00,15:00-20:00"
# HOT_TOPK=12
# HOT_COOLDOWN_MIN=8
# COOL_TOPK=8
# COOL_COOLDOWN_MIN=20
# HOT_RR_BONUS=0.0   # בונוס RR (שלילי מחמיר)
# COOL_RR_BONUS=0.1  # מוסיף דרישת RR ב־idle

TZ = os.getenv("LOCAL_TZ", "Asia/Jerusalem")

def _parse_ranges(s: str):
    rngs = []
    for part in (s or "").split(","):
        part = part.strip()
        if not part or "-" not in part: continue
        a,b = [x.strip() for x in part.split("-",1)]
        ah,am = [int(x) for x in a.split(":")]
        bh,bm = [int(x) for x in b.split(":")]
        rngs.append(((ah,am),(bh,bm)))
    return rngs

def _in_range(h:int, m:int, r:tuple[tuple[int,int],tuple[int,int]]):
    (ah,am),(bh,bm) = r
    start = ah*60+am
    end   = bh*60+bm
    cur   = h*60+m
    if end >= start:
        return start <= cur <= end
    # טווח חוצה חצות
    return cur >= start or cur <= end

def is_hot_now() -> bool:
    tz = ZoneInfo(TZ)
    now = datetime.now(tz)
    rngs = _parse_ranges(os.getenv("HOT_HOURS","09:00-12:00,15:00-20:00"))
    return any(_in_range(now.hour, now.minute, rng) for rng in rngs)

def hours_profile_now() -> dict:
    hot = is_hot_now()
    topk  = int(os.getenv("HOT_TOPK" if hot else "COOL_TOPK", "12" if hot else "8"))
    cdmin = int(os.getenv("HOT_COOLDOWN_MIN" if hot else "COOL_COOLDOWN_MIN", "8" if hot else "20"))
    rr_b  = float(os.getenv("HOT_RR_BONUS" if hot else "COOL_RR_BONUS", "0.0" if hot else "0.1"))
    return {"hot": hot, "topk": topk, "cooldown_min": cdmin, "rr_bonus": rr_b}

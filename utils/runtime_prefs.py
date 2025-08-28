# utils/runtime_prefs.py
from __future__ import annotations
import os, time
from typing import Optional
from utils.redis_client import redis_client as RED

# Keys
KEY_MUTE_UNTIL       = "algogpt:prefs:mute_until"
KEY_NEAR_OVERRIDE    = "algogpt:prefs:near_pct_override"
KEY_GRID_ALERTS      = "algogpt:prefs:grid_alerts_enabled"   # "1"/"0"
KEY_TRADE_QUIET_FMT  = "algogpt:prefs:trade_quiet:{tid}"     # "1"/"0"

def _now() -> int:
    return int(time.time())

# -------- Mute (global) --------
def set_mute(minutes: int) -> None:
    until = _now() + max(0, int(minutes)) * 60
    if RED:
        RED.set(KEY_MUTE_UNTIL, str(until))
    else:
        globals()["_MUTE_UNTIL"] = until

def clear_mute() -> None:
    if RED:
        RED.delete(KEY_MUTE_UNTIL)
    else:
        globals()["_MUTE_UNTIL"] = 0

def is_muted() -> bool:
    if RED:
        v = RED.get(KEY_MUTE_UNTIL)
        return bool(v and int(v) > _now())
    return bool(globals().get("_MUTE_UNTIL", 0) > _now())

def mute_remaining_sec() -> int:
    if RED:
        v = RED.get(KEY_MUTE_UNTIL)
        if not v: return 0
        rem = int(v) - _now()
        return rem if rem > 0 else 0
    rem = globals().get("_MUTE_UNTIL", 0) - _now()
    return rem if rem > 0 else 0

# -------- Near override --------
def set_near_pct_override(pct: float | None) -> None:
    if pct is None:
        if RED: RED.delete(KEY_NEAR_OVERRIDE)
        else: globals().pop("_NEAR_OVERRIDE", None)
        return
    pct = max(0.01, float(pct))
    if RED:
        RED.set(KEY_NEAR_OVERRIDE, f"{pct:.6f}")
    else:
        globals()["_NEAR_OVERRIDE"] = pct

def get_near_pct_override() -> Optional[float]:
    if RED:
        v = RED.get(KEY_NEAR_OVERRIDE)
        return float(v) if v else None
    return globals().get("_NEAR_OVERRIDE")

# -------- GRID alerts on/off --------
def set_grid_alerts_enabled(value: bool) -> None:
    val = "1" if value else "0"
    if RED: RED.set(KEY_GRID_ALERTS, val)
    else: globals()["_GRID_ALERTS"] = val

def is_grid_alerts_enabled() -> bool:
    if RED:
        v = RED.get(KEY_GRID_ALERTS)
        return (v or "1") == "1"  # ברירת מחדל: פעיל
    return (globals().get("_GRID_ALERTS", "1") == "1")

# -------- Trade quiet (no near) --------
def set_trade_quiet(trade_id: str, value: bool) -> None:
    key = KEY_TRADE_QUIET_FMT.format(tid=trade_id)
    val = "1" if value else "0"
    if RED: RED.set(key, val)
    else: globals()[key] = val

def is_trade_quiet(trade_id: str) -> bool:
    key = KEY_TRADE_QUIET_FMT.format(tid=trade_id)
    if RED:
        v = RED.get(key)
        return (v or "0") == "1"
    return (globals().get(key, "0") == "1")

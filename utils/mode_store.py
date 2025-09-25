# utils/mode_store.py
from __future__ import annotations
import os

# No new envs: use ROUTES_ONLY or EXECUTE_TRADES
def current_mode() -> str:
    force = (os.getenv("ROUTES_ONLY") or "").strip().lower()
    if force in ("live", "dry"): return force
    exec_trades = (os.getenv("EXECUTE_TRADES", "0").strip().lower() in ("1","true","yes","on"))
    return "live" if exec_trades else "dry"

def is_live() -> bool:
    return current_mode() == "live"

def is_dry() -> bool:
    return not is_live()




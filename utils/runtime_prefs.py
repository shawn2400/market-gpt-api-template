# utils/runtime_prefs.py
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Optional

_MUTE_UNTIL_TS: float = 0.0
_NEAR_PCT_OVERRIDE: Optional[float] = None
_TRADE_QUIET: bool = False

@dataclass
class TelePrefs:
    def is_muted(self) -> bool:
        return time.time() < _MUTE_UNTIL_TS
    def near_pct(self) -> Optional[float]:
        return _NEAR_PCT_OVERRIDE
    def trade_quiet(self) -> bool:
        return _TRADE_QUIET

def set_mute(minutes: int) -> None:
    """Mute outgoing alerts for <minutes> minutes."""
    global _MUTE_UNTIL_TS
    _MUTE_UNTIL_TS = time.time() + max(0, int(minutes)) * 60

def clear_mute() -> None:
    """Clear mute immediately."""
    global _MUTE_UNTIL_TS
    _MUTE_UNTIL_TS = 0.0

def mute_remaining_sec() -> int:
    """Seconds remaining to unmute."""
    rem = int(_MUTE_UNTIL_TS - time.time())
    return max(0, rem)

def set_near_pct_override(pct: float | None) -> None:
    """Override 'near target' threshold in percent (None to reset)."""
    global _NEAR_PCT_OVERRIDE
    _NEAR_PCT_OVERRIDE = float(pct) if pct is not None else None

def get_near_pct_override() -> Optional[float]:
    return _NEAR_PCT_OVERRIDE

def set_trade_quiet(enabled: bool) -> None:
    """If True, bot reduces noisy confirmations."""
    global _TRADE_QUIET
    _TRADE_QUIET = bool(enabled)





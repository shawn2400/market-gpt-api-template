# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
import os
import math

# מטריקות — נפילה רכה
try:
    from utils.metrics_tracker import (
        # אופציונלי: אם קיימים, נשתמש; אחרת no-op
        observe_http_ctx,  # רק למדידה סביב קריאות SDK אם תרצה
    )
except Exception:
    from contextlib import contextmanager
    @contextmanager
    def observe_http_ctx(*args, **kwargs):
        yield

# ───────────────────────── עזרי בסיס ─────────────────────────

def _swing_points(highs: List[float], lows: List[float], left: int, right: int) -> Tuple[List[int], List[int]]:
    """
    מחזיר אינדקסים של swing-high / swing-low לפי left/right (pivot points).
    """
    sh_idx: List[int] = []
    sl_idx: List[int] = []
    n = len(highs)
    for i in range(left, n - right):
        hv = highs[i]
        lv = lows[i]
        is_sh = all(hv >= highs[i - j] for j in range(1, left + 1)) and all(hv > highs[i + j] for j in range(1, right + 1))
        is_sl = all(lv <= lows[i - j] for j in range(1, left + 1)) and all(lv < lows[i + j] for j in range(1, right + 1))
        if is_sh:
            sh_idx.append(i)
        if is_sl:
            sl_idx.append(i)
    return sh_idx, sl_idx

def _last_struct_level(kl: List[List[Any]], side_txt: str,
                       left: int, right: int, lookback: int) -> Optional[float]:
    """
    מחזיר רמת SL מבנית אחרונה: ל־LONG – swing-low אחרון; ל־SHORT – swing-high אחרון.
    """
    if not kl:
        return None
    highs = [float(k[2]) for k in kl]
    lows  = [float(k[3]) for k in kl]
    sh, sl = _swing_points(highs, lows, left, right)
    # מגבילים ללוקבאק אחרון
    n = len(kl)
    cutoff = max(0, n - int(max(lookback, left + right + 3)))
    sh = [i for i in sh if i >= cutoff]
    sl = [i for i in sl if i >= cutoff]
    if side_txt.upper() == "BUY":
        if not sl:
            return None
        # נעדיף הנמוך מבין ה־recent lows (שמרני)
        return float(min(lows[i] for i in sl))
    else:
        if not sh:
            return None
        # נעדיף הגבוה מבין ה־recent highs
        return float(max(highs[i] for i in sh))

def _merge_struct_with_be(side_txt: str, be_price: float, struct_price: Optional[float], mode: str) -> float:
    """
    מצב מיזוג:
      - "tight": לונג → max(be, struct); שורט → min(be, struct)
      - "loose": לונג → min(be, struct); שורט → max(be, struct)
      - "be_only": מתעלם מ־struct
      - "struct_only": מתעלם מ־be אם קיים struct, אחרת be
    """
    s = side_txt.upper()
    m = (mode or "tight").lower()
    if struct_price is None:
        return float(be_price)
    if m == "be_only":
        return float(be_price)
    if m == "struct_only":
        return float(struct_price)
    if s == "BUY":
        if m == "tight":
            return float(max(be_price, struct_price))
        else:
            return float(min(be_price, struct_price))
    else:
        if m == "tight":
            return float(min(be_price, struct_price))
        else:
            return float(max(be_price, struct_price))

def _apply_buffer_bps(side_txt: str, price: float, bps: float) -> float:
    if bps <= 0:
        return float(price)
    if side_txt.upper() == "BUY":
        return float(price * (1.0 - bps / 10_000.0))
    else:
        return float(price * (1.0 + bps / 10_000.0))

# ───────────────────────── ממשק ציבורי ─────────────────────────

def compute_structural_sl(klines: List[List[Any]],
                          side_txt: str,
                          *,
                          left: int = 3,
                          right: int = 3,
                          lookback: int = 50,
                          buffer_bps: float = 0.0) -> Optional[float]:
    """
    מחזיר רמת SL מבנית אחרונה (עם buffer_bps אם נדרש). אם אין מספיק נתונים – None.
    """
    base = _last_struct_level(klines, side_txt, left=left, right=right, lookback=lookback)
    if base is None:
        return None
    return float(_apply_buffer_bps(side_txt, base, float(buffer_bps)))

def choose_stop_price(be_price: float,
                      struct_price: Optional[float],
                      side_txt: str,
                      *,
                      merge_mode: str = "tight") -> float:
    """
    מאחד בין BE לבין Structural לפי merge_mode.
    """
    return _merge_struct_with_be(side_txt, be_price, struct_price, merge_mode)

# ───────────────────────── Time-Stop בסיסי ─────────────────────────

def should_time_stop(entry_time_ms: Optional[int],
                     now_ms: int,
                     hold_minutes: int) -> bool:
    """
    בודק אם עברו hold_minutes מאז פתיחת הפוזיציה.
    entry_time_ms יכול להגיע מ־position info (או None – ואז חוזר False).
    """
    if not entry_time_ms or hold_minutes <= 0:
        return False
    try:
        return (now_ms - int(entry_time_ms)) >= int(hold_minutes) * 60_000
    except Exception:
        return False

def time_stop_decision(side_txt: str,
                       entry_price: float,
                       price_now: float,
                       *,
                       profit_lock_min_pct: float = 0.0) -> str:
    """
    החלטה בסיסית כשמגיע ה־time-stop:
      - אם הפוזיציה ברווח מעל profit_lock_min_pct → "KEEP" (לא לגעת).
      - אחרת → "MOVE_BE" (להקפיץ SL ל־BE) — או STRUCT אם יש מחוץ לפה.
    """
    if profit_lock_min_pct <= 0 or price_now <= 0 or entry_price <= 0:
        return "MOVE_BE"
    s = side_txt.upper()
    chg_pct = (price_now / entry_price - 1.0) * (100.0 if s == "BUY" else -100.0)
    if chg_pct >= profit_lock_min_pct:
        return "KEEP"
    return "MOVE_BE"

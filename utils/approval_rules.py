# utils/approval_rules.py
from __future__ import annotations
import os, time
from typing import Dict, Tuple, List

def _bool(env: str) -> bool:
    return os.getenv(env, "").strip().lower() in ("1", "true", "yes", "on")

def _float(env: str, default: float | None = None) -> float | None:
    v = os.getenv(env, "")
    try:
        return float(v)
    except Exception:
        return default

def _parse_ranges(spec: str) -> List[tuple[int,int]]:
    out: List[tuple[int,int]] = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                out.append((int(a), int(b)))
            except Exception:
                pass
        else:
            try:
                h = int(part)
                out.append((h, h))
            except Exception:
                pass
    return out

def _in_ranges(hour: int, ranges: List[tuple[int,int]]) -> bool:
    for a, b in ranges:
        if a <= hour <= b:
            return True
    return False

def should_auto_approve(req: Dict) -> Tuple[bool, str]:
    """
    כללים (כולם כבויים כברירת מחדל):
    - TELEGRAM_AUTO_APPROVE=1 => תמיד
    - AUTO_APPROVE_BUDGET_MAX_USD: אם budget_usd <= סף => כן
    - AUTO_APPROVE_NIGHT=1 + NIGHT_HOURS="00-06,22-23": אם בשעות האלה => כן
    - AUTO_APPROVE_TIER="trusted"/"gold" => כן
    """
    if _bool("TELEGRAM_AUTO_APPROVE"):
        return True, "env_auto_approve"

    budget = float(req.get("budget_usd", 0.0) or 0.0)
    thr = _float("AUTO_APPROVE_BUDGET_MAX_USD", None)
    if (thr is not None) and (budget <= thr):
        return True, f"budget_le_{thr}"

    if _bool("AUTO_APPROVE_NIGHT"):
        spec = os.getenv("NIGHT_HOURS", "00-06")
        ranges = _parse_ranges(spec)
        h = time.localtime().tm_hour
        if _in_ranges(h, ranges):
            return True, f"night_hours_{spec}"

    tier = os.getenv("AUTO_APPROVE_TIER", "").strip().lower()
    if tier in ("trusted", "gold"):
        return True, f"tier_{tier}"

    return False, ""


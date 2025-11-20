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
    🚀 100% DYNAMIC Market-Driven Auto-Approval Rules:
    - TELEGRAM_AUTO_APPROVE=1 => Always approve
    - AUTO_APPROVE_BUDGET_MAX_USD: If budget_usd <= threshold => Approve
    - AUTO_APPROVE_TIER="trusted"/"gold" => Approve
    
    ❌ REMOVED: AUTO_APPROVE_NIGHT (time-based logic eliminated)
    """
    if _bool("TELEGRAM_AUTO_APPROVE"):
        return True, "env_auto_approve"

    budget = float(req.get("budget_usd", 0.0) or 0.0)
    thr = _float("AUTO_APPROVE_BUDGET_MAX_USD", None)
    if (thr is not None) and (budget <= thr):
        return True, f"budget_le_{thr}"

    tier = os.getenv("AUTO_APPROVE_TIER", "").strip().lower()
    if tier in ("trusted", "gold"):
        return True, f"tier_{tier}"

    return False, ""


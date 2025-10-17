# utils/learning_loops.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, time, random
from contextlib import suppress
from typing import Dict, Any, Optional, Tuple, List

# Redis (אופציונלי)
try:
    import redis  # type: ignore
except Exception:
    redis = None  # type: ignore

NS = os.getenv("REDIS_NAMESPACE", "algogpt")
REDIS_URL = os.getenv("REDIS_URL", "").strip()

def _get_r():
    if not (redis and REDIS_URL):
        return None
    try:
        return redis.Redis.from_url(REDIS_URL, decode_responses=True)
    except Exception:
        return None

# ───────────────────── Shadow Executor (105) ─────────────────────
def shadow_log_scenario(symbol: str, side: str, profile: Dict[str, Any], meta: Optional[Dict[str, Any]] = None) -> None:
    """
    שומר “צל” של פרופיל ניהול חלופי לצורך השוואה בדיעבד.
    לא מבצע הזמנות אמיתיות; רק לוג קצר (Redis/in-mem).
    """
    rec = {
        "ts": time.time(),
        "symbol": symbol.upper(),
        "side": side.upper(),
        "profile": dict(profile),
        "meta": meta or {},
    }
    r = _get_r()
    if r:
        key = f"{NS}:shadow:scenarios"
        try:
            r.lpush(key, json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
            r.ltrim(key, 0, int(os.getenv("SHADOW_MAX", "500")) - 1)
        except Exception:
            pass
    # in-memory fallback עדין — לא נשמר כאן כדי להישאר סטטיים

def shadow_log_outcome(symbol: str, side: str, realized_R: float) -> None:
    """
    נרשום תוצאת טרייד (R) כדי לאמוד בדיעבד מי מהפרופילים היה עדיף.
    """
    r = _get_r()
    rec = {"ts": time.time(), "symbol": symbol.upper(), "side": side.upper(), "R": float(realized_R)}
    if r:
        try:
            r.lpush(f"{NS}:shadow:outcomes", json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
            r.ltrim(f"{NS}:shadow:outcomes", 0, int(os.getenv("SHADOW_OUTCOME_MAX", "2000")) - 1)
        except Exception:
            pass

# ───────────────────── Policy Bandit (106/“ε-greedy”) ─────────────────────
def _bandit_key(ctx_hash: str) -> str:
    return f"{NS}:bandit:{ctx_hash}"

def _ctx_hash(regime: Optional[int] = None, session: Optional[str] = None) -> str:
    return f"r{regime or -1}|s{(session or 'NA').lower()}"

def bandit_select(regime: Optional[int], session: Optional[str], candidates: List[str]) -> str:
    """
    בוחר פרופיל לפי ε-greedy פשוט:
      ε מתוך ENV (BANDIT_EPS=0.08) → אקראי; אחרת — argmax(reward/plays).
    """
    if not candidates:
        return "BASE"
    eps = float(os.getenv("BANDIT_EPS", "0.08") or 0.08)
    ctx = _ctx_hash(regime, session)
    if random.random() < eps:
        return random.choice(candidates)
    r = _get_r()
    best = candidates[0]
    best_score = -1e9
    for name in candidates:
        plays, reward = 0, 0.0
        if r:
            try:
                data = r.hget(_bandit_key(ctx), name)
                if data:
                    obj = json.loads(data)
                    plays = int(obj.get("plays", 0))
                    reward = float(obj.get("reward", 0.0))
            except Exception:
                pass
        score = (reward / max(1, plays)) if plays > 0 else 0.0
        if score > best_score:
            best_score, best = score, name
    return best

def bandit_update(regime: Optional[int], session: Optional[str], chosen: str, reward_R: float) -> None:
    ctx = _ctx_hash(regime, session)
    r = _get_r()
    if not r:
        return
    key = _bandit_key(ctx)
    try:
        cur = r.hget(key, chosen)
        obj = json.loads(cur) if cur else {"plays": 0, "reward": 0.0}
        obj["plays"] = int(obj.get("plays", 0)) + 1
        obj["reward"] = float(obj.get("reward", 0.0)) + float(reward_R)
        r.hset(key, chosen, json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        r.expire(key, int(os.getenv("BANDIT_TTL_SEC", "172800")) or 172800)  # יומיים
    except Exception:
        pass

# עזר: חשב “session” בסיסי מהשעה (Asia/EU/US)
def map_session_from_hour(utc_hour: int) -> str:
    if 0 <= utc_hour < 8:
        return "ASIA"
    if 8 <= utc_hour < 16:
        return "EU"
    return "US"

__all__ = [
    "shadow_log_scenario", "shadow_log_outcome",
    "bandit_select", "bandit_update", "map_session_from_hour",
]

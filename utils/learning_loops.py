# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import json
import time
from contextlib import suppress
from typing import Dict, Any, Tuple, Optional, List

# Redis (אופציונלי)
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

# === קונפיג/ENV ===
NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL = (os.getenv("REDIS_URL") or "").strip()
BANDIT_EPSILON = float(os.getenv("BANDIT_EPSILON", "0.12") or 0.12)
BANDIT_MIN_PLAYS = int(os.getenv("BANDIT_MIN_PLAYS", "10") or 10)
BANDIT_DECAY = float(os.getenv("BANDIT_DECAY", "0.995") or 0.995)  # שכחה איטית
SHADOW_ENABLE = os.getenv("SHADOW_ENABLE", "1").lower() in ("1","true","yes","on")
SHADOW_SAMPLE_PCT = float(os.getenv("SHADOW_SAMPLE_PCT", "0.5") or 0.5)  # חלק מהאירועים

# קבצי fallback (אם אין Redis)
import pathlib
DATA_DIR = pathlib.Path("data/learning")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# === עזרי Redis ===
_redis_cached = None
async def _get_redis():
    global _redis_cached
    if _redis_cached:
        return _redis_cached
    if not (aioredis and REDIS_URL):
        return None
    _redis_cached = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis_cached

def _ctx_key(context: Dict[str, Any]) -> str:
    # context כולל: regime (MR/CH/TREND), session (ASIA/EU/US/OTHER)
    reg = str(context.get("regime", "UNK")).upper()
    ses = str(context.get("session", "UNK")).upper()
    return f"{NS}:bandit:{reg}:{ses}"

# === מבנה מצב ה-Bandit ===
# נשמור json כמו:
# {"arms": {"BASE":{"n":12,"avg":0.18}, "EXTREME":{"n":9,"avg":0.22}}, "updated": 171111.11}
def _default_state(candidates: List[str]) -> Dict[str, Any]:
    return {
        "arms": {c: {"n": 0, "avg": 0.0} for c in candidates},
        "updated": time.time(),
        "version": 1,
    }

async def _load_state(context: Dict[str, Any], candidates: List[str]) -> Dict[str, Any]:
    r = await _get_redis()
    key = _ctx_key(context)
    if r:
        try:
            raw = await r.get(key)
            if raw:
                obj = json.loads(raw)
                # ensure all candidates exist
                for c in candidates:
                    obj.setdefault("arms", {}).setdefault(c, {"n": 0, "avg": 0.0})
                return obj
        except Exception:
            pass
    # fallback file
    f = DATA_DIR / f"bandit_{key.replace(':','_')}.json"
    if f.exists():
        with suppress(Exception):
            obj = json.loads(f.read_text(encoding="utf-8"))
            for c in candidates:
                obj.setdefault("arms", {}).setdefault(c, {"n": 0, "avg": 0.0})
            return obj
    return _default_state(candidates)

async def _save_state(context: Dict[str, Any], state: Dict[str, Any]) -> None:
    state["updated"] = time.time()
    r = await _get_redis()
    key = _ctx_key(context)
    raw = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    if r:
        with suppress(Exception):
            await r.set(key, raw)
            await r.expire(key, int(os.getenv("BANDIT_STATE_TTL_SEC", "1209600") or 1209600))  # 14d
            return
    # file fallback
    f = DATA_DIR / f"bandit_{key.replace(':','_')}.json"
    with suppress(Exception):
        f.write_text(raw, encoding="utf-8")

# === בחירה ε-greedy + decay ===
def _choose_arm(state: Dict[str, Any], candidates: List[str]) -> str:
    import random
    # חקירה
    if random.random() < BANDIT_EPSILON:
        return random.choice(candidates)

    # אקספלויט: בחר avg הגבוה ביותר (אם n < BANDIT_MIN_PLAYS תן יתרון קל למילוי)
    best = None
    best_val = -1e9
    for c in candidates:
        arm = state["arms"].get(c, {"n": 0, "avg": 0.0})
        est = float(arm.get("avg", 0.0))
        # בונוס קטן לזרועות שעוד לא קיבלו מספיק דגימות
        if int(arm.get("n", 0)) < BANDIT_MIN_PLAYS:
            est += 0.05
        if est > best_val:
            best, best_val = c, est
    return best or candidates[0]

async def bandit_select(context: Dict[str, Any],
                        candidates: List[str]) -> Tuple[str, Dict[str, Any]]:
    """
    בחירת זרוע (פרופיל) ע"פ ε-greedy. מחזיר (name, meta)
    meta: {"arms":..., "epsilon":..., "context":...}
    """
    state = await _load_state(context, candidates)
    choice = _choose_arm(state, candidates)
    meta = {
        "epsilon": BANDIT_EPSILON,
        "arms": state.get("arms", {}),
        "context": context,
    }
    return choice, meta

async def bandit_update(context: Dict[str, Any], arm: str, reward: float) -> None:
    """
    עדכון ממוצע רץ עם decay (מקטין משקל עבר).
    reward מומלץ: R-multiple ממוצע/normalized outcome ∈ [-1..+2] (קלמפ ל-[-2..+3]).
    """
    try:
        r = max(-2.0, min(3.0, float(reward)))
    except Exception:
        return
    state = await _load_state(context, [arm])
    arms = state.setdefault("arms", {})
    a = arms.setdefault(arm, {"n": 0, "avg": 0.0})

    # decay קטן: avg ← avg*decay + r*(1-decay)
    old_avg = float(a.get("avg", 0.0))
    new_avg = old_avg * BANDIT_DECAY + r * (1.0 - BANDIT_DECAY)
    a["avg"] = float(new_avg)
    a["n"] = int(a.get("n", 0)) + 1
    await _save_state(context, state)

# === Shadow (רק רישום "מה אם") ===
def _shadow_file(context: Dict[str, Any]) -> pathlib.Path:
    reg = str(context.get("regime", "UNK")).upper()
    ses = str(context.get("session", "UNK")).upper()
    return DATA_DIR / f"shadow_{reg}_{ses}.jsonl"

def should_shadow() -> bool:
    import random
    if not SHADOW_ENABLE:
        return False
    return random.random() < SHADOW_SAMPLE_PCT

def shadow_log(context: Dict[str, Any],
               chosen: str,
               alt: str,
               indicators: Dict[str, float],
               profile_detail: Dict[str, Any]) -> None:
    """
    רישום דל־משקל: מי נבחר ומה האלטרנטיבה + אינדיקטורים/פרופיל.
    """
    rec = {
        "ts": time.time(),
        "ctx": context,
        "chosen": chosen,
        "alt": alt,
        "ind": indicators,
        "profile": profile_detail,
    }
    try:
        f = _shadow_file(context)
        with f.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

# === עזרי הקשר (regime × session) ===
def resolve_session_bucket(utc_hour: int) -> str:
    # גס אך מועיל: ASIA 0–7, EU 7–15, US 13–21, אחר = OTHER
    h = int(max(0, min(23, utc_hour)))
    if 0 <= h < 7:
        return "ASIA"
    if 7 <= h < 13:
        return "EU"
    if 13 <= h < 21:
        return "US"
    return "OTHER"

def resolve_regime(adx: float, atr_pct: float,
                   adx_trend: float = 22.0, chop_atr_pct: float = 0.6) -> str:
    try:
        a = float(adx)
        p = float(atr_pct)
    except Exception:
        return "CH"
    if a >= adx_trend and p >= chop_atr_pct:
        return "TREND"
    if p < chop_atr_pct:
        return "CH"
    return "MR"  # mean-revert

__all__ = [
    "bandit_select","bandit_update","should_shadow","shadow_log",
    "resolve_session_bucket","resolve_regime"
]


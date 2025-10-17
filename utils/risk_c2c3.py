# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, math, logging
from typing import Dict, Any, List, Tuple, Optional
from contextlib import suppress

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

logger = logging.getLogger("algogpt.risk_c2c3")

NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web")
REDIS_URL = (os.getenv("REDIS_URL") or "").strip()

# ==== ENV ====
C2_ENABLE = os.getenv("RISK_C2_CORR_HALT", "1").lower() in ("1","true","yes","on")
C2_WINDOW_SEC = int(os.getenv("C2_WINDOW_SEC", "900") or 900)              # 15m
C2_MAX_OPEN_CLUSTER = int(os.getenv("C2_MAX_OPEN_CLUSTER", "3") or 3)      # כמה סמלים בקלאסטר
C2_MAX_DD_CLUSTER_USD = float(os.getenv("C2_MAX_DD_CLUSTER_USD", "250") or 250.0)
C2_CORR_TAGS = [t.strip().upper() for t in (os.getenv("C2_CORR_TAGS","BTC,ETH,SOL,BNB")).split(",") if t.strip()]

C3_ENABLE = os.getenv("RISK_C3_EXPECT_GUARD", "1").lower() in ("1","true","yes","on")
C3_FAIL_RATE_MAX = float(os.getenv("C3_FAIL_RATE_MAX", "0.6") or 0.6)      # יחס כשל אופטימלי מקסימלי
C3_SAMPLE_MIN = int(os.getenv("C3_SAMPLE_MIN", "10") or 10)                # מינימום דגימות
C3_SCOPE = os.getenv("C3_SCOPE", "SYMBOL").upper()                         # SYMBOL/PROFILE/GLOBAL
C3_WINDOW_SEC = int(os.getenv("C3_WINDOW_SEC", "7200") or 7200)            # 2h

# מפתחות Redis
def _rkey(prefix: str, *parts: str) -> str:
    base = ":".join([NS, "risk", prefix] + [p for p in parts if p])
    return base

async def _get_redis():
    if not (aioredis and REDIS_URL):
        return None
    return aioredis.from_url(REDIS_URL, decode_responses=True)

# ===== C2: Correlated Halt =====================================================
async def c2_should_halt(symbol: str, open_positions: List[Dict[str, Any]], cluster_tag: Optional[str] = None) -> Tuple[bool, str]:
    """
    בולם פתיחת טרייד חדש אם:
      1) יש יותר מדי פוזיציות באותו קלאסטר (מעין "קורלציה" לפי תג),
      2) או שה-P/L של הקלאסטר ב-X דקה אחרונות שלילי מעבר לסף.
    """
    if not C2_ENABLE:
        return False, "C2_DISABLED"

    sym = (symbol or "").upper()
    tag = (cluster_tag or (sym[:-4] if sym.endswith("USDT") else sym)).upper()
    if tag not in C2_CORR_TAGS:
        # אין טאג משותף — לא בולם
        return False, "C2_TAG_NOT_TRACKED"

    # 1) ספירת קלאסטר
    in_cluster = []
    for p in open_positions or []:
        s = str(p.get("symbol","")).upper()
        t = (s[:-4] if s.endswith("USDT") else s)
        if t.upper() == tag:
            in_cluster.append(p)
    if len(in_cluster) >= C2_MAX_OPEN_CLUSTER:
        return True, f"C2_CLUSTER_SIZE>={C2_MAX_OPEN_CLUSTER}"

    # 2) Drawdown בקלאסטר (Best-effort מחישוב מהיר אם יש unrealizedPNL)
    try:
        dd = 0.0
        for p in in_cluster:
            with suppress(Exception):
                dd += float(p.get("unRealizedProfit") or 0.0)
        if dd < 0 and abs(dd) >= C2_MAX_DD_CLUSTER_USD:
            return True, f"C2_CLUSTER_DD>{C2_MAX_DD_CLUSTER_USD}"
    except Exception:
        pass

    return False, "OK"

# ===== C3: Expectation Guard ===================================================
async def c3_expectation_ok(symbol: str, profile_name: str) -> Tuple[bool, str]:
    """
    בודק יחס הצלחה "טרי" (חלון זמן). אפשר לפי SYMBOL/PROFILE/GLOBAL.
    מניח שבאירועי ביצוע אנחנו קוראים ל-record_outcome(...) (ראה בהמשך).
    """
    if not C3_ENABLE:
        return True, "C3_DISABLED"
    r = await _get_redis()
    if not r:
        return True, "NO_REDIS"

    now = int(time.time())
    scope = C3_SCOPE
    key = None
    if scope == "SYMBOL":
        key = _rkey("c3:outcomes", "sym", (symbol or "").upper())
    elif scope == "PROFILE":
        key = _rkey("c3:outcomes", "prof", (profile_name or "BASE").upper())
    else:
        key = _rkey("c3:outcomes", "global")

    try:
        # נשמור כ-list של json {"ts":..,"ok":0/1}
        raw = await r.lrange(key, 0, 999)
    except Exception:
        return True, "C3_READ_ERR"

    # סינון לפי חלון זמן
    ok_cnt = 0
    tot = 0
    for s in raw:
        with suppress(Exception):
            o = json.loads(s)
            if now - int(o.get("ts", 0)) <= C3_WINDOW_SEC:
                tot += 1
                ok_cnt += 1 if int(o.get("ok", 0)) == 1 else 0

    if tot < C3_SAMPLE_MIN:
        return True, "C3_NOT_ENOUGH_DATA"

    fail_rate = 1.0 - (ok_cnt / float(tot))
    if fail_rate > C3_FAIL_RATE_MAX:
        return False, f"C3_FAIL_RATE={fail_rate:.2f}>MAX={C3_FAIL_RATE_MAX:.2f}"
    return True, "OK"

# קריאה מאירוע ביצוע (TP/SL) — רושם הצלחה/כישלון לחלון ה-C3
async def record_outcome(symbol: str, profile_name: str, ok: bool) -> None:
    r = await _get_redis()
    if not r:
        return
    ok_i = 1 if ok else 0
    ts = int(time.time())
    items = [
        (_rkey("c3:outcomes", "global"), {"ts": ts, "ok": ok_i}),
        (_rkey("c3:outcomes", "sym", (symbol or "").upper()), {"ts": ts, "ok": ok_i}),
        (_rkey("c3:outcomes", "prof", (profile_name or "BASE").upper()), {"ts": ts, "ok": ok_i}),
    ]
    for key, obj in items:
        with suppress(Exception):
            await r.lpush(key, json.dumps(obj, ensure_ascii=False))
            await r.ltrim(key, 0, 999)
            await r.expire(key, C3_WINDOW_SEC * 3)

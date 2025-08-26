# workers/gpt_auto_suggest.py
from __future__ import annotations
import os, json, math, time, hmac, hashlib, base64, asyncio, logging, random
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

import httpx
from openai import AsyncOpenAI

# --------- Watchlist helpers (with safe fallbacks) ----------
try:
    from utils.watchlist_utils import build_symbol_pool, get_symbol_prefs, load_watchlist
except Exception:
    from utils.watchlist_utils import load_watchlist  # type: ignore
    def build_symbol_pool(k=12, min_quality=6, include_anchor=True, include_shorts=True, balanced=True, explore_prob=0.15):
        wl = load_watchlist(min_quality=min_quality)
        return [it["symbol"] for it in wl][:k]
    def get_symbol_prefs(symbol: str) -> dict:
        return {}

from utils.indicators import prepare_indicators_for_backtest
from utils.anchor import evaluate_anchor

# --------- Redis (optional) ----------
try:
    from utils.redis_client import redis_client as RED  # expects REDIS_URL in env
except Exception:
    RED = None

# ================= ENV / CONFIG =================
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL     = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))

# Adaptive concurrency
OPENAI_CONC_MIN  = int(float(os.getenv("OPENAI_CONC_MIN", "2")))
OPENAI_CONC_MAX  = int(float(os.getenv("OPENAI_CONC_MAX", "4")))
GPT_P95_SLOW_S   = float(os.getenv("GPT_P95_SLOW_SECONDS", "3.5"))
GPT_P95_FAST_S   = float(os.getenv("GPT_P95_FAST_SECONDS", "2.0"))

# Sweep cadence & pool
SUGGEST_INTERVAL_SECONDS = int(float(os.getenv("SUGGEST_INTERVAL_SECONDS", "600")))
TOPK_PER_SWEEP           = int(float(os.getenv("TOPK_PER_SWEEP", "16")))
TOPK_MAX_BOOST           = int(float(os.getenv("TOPK_MAX_BOOST", "8")))
SWEEP_CAP                = int(float(os.getenv("SWEEP_CAP", "999")))

# Gating (base)
MIN_SUCCESS_PCT   = float(os.getenv("MIN_SUCCESS_PCT", "70"))
MIN_RR            = float(os.getenv("MIN_RR", "1.8"))
SPOT_MIN_RR       = float(os.getenv("SPOT_MIN_RR", "1.5"))
ELITE_RR          = float(os.getenv("ELITE_RR", "2.4"))
SUCCESS_DELTA_ON_ELITE = float(os.getenv("SUCCESS_DELTA_ON_ELITE", "3"))
ANCHOR_MODE       = os.getenv("ANCHOR_MODE", "soft").lower()

# Gating (entry distance, no chase) — באחוזים
FUT_LOW_MAX_DIST  = float(os.getenv("FUT_LOW_MAX_DIST", "0.45"))
FUT_MID_MAX_DIST  = float(os.getenv("FUT_MID_MAX_DIST", "0.60"))
FUT_HIGH_MAX_DIST = float(os.getenv("FUT_HIGH_MAX_DIST", "0.80"))
SPOT_LOW_MAX_DIST  = float(os.getenv("SPOT_LOW_MAX_DIST", "0.70"))
SPOT_MID_MAX_DIST  = float(os.getenv("SPOT_MID_MAX_DIST", "0.90"))
SPOT_HIGH_MAX_DIST = float(os.getenv("SPOT_HIGH_MAX_DIST", "1.20"))

# RR per volatility regime (tighten on high)
RR_LOW  = float(os.getenv("RR_LOW",  str(SPOT_MIN_RR)))  # e.g., 1.5
RR_MID  = float(os.getenv("RR_MID",  str(MIN_RR)))       # e.g., 1.8
RR_HIGH = float(os.getenv("RR_HIGH", "2.1"))

# Cooldown / Dedup
COOLDOWN_MINUTES = int(float(os.getenv("COOLDOWN_MINUTES", "30")))
DEDUP_TTL_MIN    = int(float(os.getenv("DEDUP_TTL_MIN", "180")))

# Caps (notional & alerts)
MAX_DAILY_ALERTS              = int(float(os.getenv("MAX_DAILY_ALERTS", "0")))  # 0=off
MAX_DAILY_NOTIONAL            = float(os.getenv("MAX_DAILY_NOTIONAL", "0"))
MAX_DAILY_NOTIONAL_PER_SYMBOL = float(os.getenv("MAX_DAILY_NOTIONAL_PER_SYMBOL", "0"))
ALERTS_PER_SYMBOL_BASE        = int(float(os.getenv("ALERTS_PER_SYMBOL_BASE", "3")))
ALERTS_PER_SYMBOL_BONUS_Q8    = int(float(os.getenv("ALERTS_PER_SYMBOL_BONUS_Q8", "2")))
ALERTS_PER_SYMBOL_FLOOR_Q6    = int(float(os.getenv("ALERTS_PER_SYMBOL_FLOOR_Q6", "2")))

# Context
CORE_TOPK_URL     = os.getenv("CORE_TOPK_URL", "").strip()
CORE_TOPK_TOKEN   = os.getenv("CORE_TOPK_TOKEN", "").strip()
CONTEXT_URL       = os.getenv("CONTEXT_URL", "").strip()
CONTEXT_TOKEN     = os.getenv("CONTEXT_TOKEN", "").strip()
CONTEXT_BATCH_URL = os.getenv("CONTEXT_BATCH_URL", "").strip()
CONTEXT_BATCH_Q   = int(float(os.getenv("CONTEXT_BATCH_Q", "16")))

# Binance HTTP
BINANCE_FUTURES_HTTP_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

# Outgoing (Sink/Telegram)
OUTGOING_WEBHOOK_URL = os.getenv("OUTGOING_WEBHOOK_URL", "").strip()
OUTGOING_TOKEN       = os.getenv("OUTGOING_TOKEN", "").strip()
HMAC_SECRET          = os.getenv("OUTBOUND_HMAC_SECRET", "").encode() if os.getenv("OUTBOUND_HMAC_SECRET") else None

# Modes
SUGGEST_MODES = [m.strip().upper() for m in os.getenv("SUGGEST_MODES", "FUTURES,SPOT,GRID").split(",") if m.strip()]

# TZ
TZ = os.getenv("LOCAL_TZ", "Asia/Jerusalem")

# Logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gpt_auto_suggest")

# ================= STATE =================
CUR_CONC = max(OPENAI_CONC_MIN, min(OPENAI_CONC_MAX, OPENAI_CONC_MAX))  # נתחיל במקס
_LAT_SAMPLES: List[float] = []  # למדידת p95
_COOLDOWN: Dict[str, float] = {}     # local fallback
_DEDUP: Dict[str, float]    = {}     # local fallback
_DAILY: Dict[str, float]    = {}     # local fallback
_SENT_THIS_SWEEP = 0
_LAST_SWEEPS_SENT: List[int] = []    # לצורך boost

# ================= Utils =================
def _now_ts() -> float:
    return time.time()

def _yyyymmdd_now() -> str:
    dt = datetime.now(timezone.utc).astimezone()
    return dt.strftime("%Y%m%d")

def _p95(xs: List[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    idx = max(0, min(len(s)-1, int(math.ceil(0.95*len(s)) - 1)))
    return s[idx]

def rr_val(entry: float, sl: float, tp1: float) -> float:
    try:
        risk = abs(entry - sl); reward = abs(tp1 - entry)
        return reward / risk if risk > 0 else 0.0
    except Exception:
        return 0.0

def _sign_hmac(body: bytes) -> str:
    if not HMAC_SECRET:
        return ""
    mac = hmac.new(HMAC_SECRET, body, hashlib.sha256).digest()
    return "sha256=" + base64.b64encode(mac).decode()

def _idem_key(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]

# ----- Redis-backed counters -----
def _get_counter(key: str) -> float:
    if RED:
        try:
            v = RED.get(key)
            return float(v or 0.0)
        except Exception:
            pass
    return _DAILY.get(key, 0.0)

def _inc_counter(key: str, val: float, ttl: Optional[int] = None) -> None:
    if RED:
        try:
            RED.incrbyfloat(key, float(val))
            if ttl:
                RED.expire(key, ttl)
            return
        except Exception:
            pass
    _DAILY[key] = _DAILY.get(key, 0.0) + float(val)

# ----- Cooldown / Dedup -----
def _in_cooldown(sym: str) -> bool:
    if RED:
        try:
            t = RED.get(f"cd:{sym}")
            return bool(t and (_now_ts() - float(t) < COOLDOWN_MINUTES*60))
        except Exception:
            pass
    t = _COOLDOWN.get(sym)
    return bool(t and (_now_ts() - t < COOLDOWN_MINUTES*60))

def _touch_cooldown(sym: str) -> None:
    if RED:
        try:
            RED.set(f"cd:{sym}", str(_now_ts()), ex=COOLDOWN_MINUTES*60)
            return
        except Exception:
            pass
    _COOLDOWN[sym] = _now_ts()

def _dedup_key(sym: str, side: str, trade_type: str, entry: float, sl: float, tp1: float, tp2: float, tp3: float, lev: Optional[int]) -> str:
    raw = f"{sym}|{side}|{trade_type}|{entry:.8f}|{sl:.8f}|{tp1:.8f}|{tp2:.8f}|{tp3:.8f}|{lev or 0}"
    return hashlib.sha256(raw.encode()).hexdigest()

def _seen_dedup(h: str) -> bool:
    if RED:
        try:
            return bool(RED.get(f"du:{h}"))
        except Exception:
            return False
    ts_old = _DEDUP.get(h)
    return bool(ts_old and (_now_ts() - ts_old) < (DEDUP_TTL_MIN*60))

def _mark_dedup(h: str) -> None:
    if RED:
        try:
            RED.set(f"du:{h}", "1", ex=DEDUP_TTL_MIN*60)
            return
        except Exception:
            pass
    _DEDUP[h] = _now_ts()

# ----- Caps -----
def _cap_ok(notional: float, sym: str, qscore: Optional[int]) -> bool:
    day = _yyyymmdd_now()
    # תקרה כללית בנוטיונל
    if MAX_DAILY_NOTIONAL > 0:
        key = f"cap:all:{day}"
        cur = _get_counter(key)
        if cur + notional > MAX_DAILY_NOTIONAL:
            log.info({"event":"cap_block_all","cur":cur,"ask":notional,"cap":MAX_DAILY_NOTIONAL})
            return False
    # תקרה נוטיונלית פר־סימבול
    if MAX_DAILY_NOTIONAL_PER_SYMBOL > 0:
        key = f"capn:{sym}:{day}"
        cur = _get_counter(key)
        if cur + notional > MAX_DAILY_NOTIONAL_PER_SYMBOL:
            log.info({"event":"cap_block_sym_notional","sym":sym,"cur":cur,"ask":notional,"cap":MAX_DAILY_NOTIONAL_PER_SYMBOL})
            return False
    # תקרת alerts פר־סימבול לפי איכות
    if MAX_DAILY_ALERTS > 0:
        base = ALERTS_PER_SYMBOL_BASE
        if isinstance(qscore, int):
            if qscore >= 8: base += ALERTS_PER_SYMBOL_BONUS_Q8
            elif qscore <= 6: base = max(ALERTS_PER_SYMBOL_FLOOR_Q6, base-1)
        key = f"cnt:{sym}:{day}"
        cur = _get_counter(key)
        if cur >= base:
            log.info({"event":"cap_alerts_per_symbol_block","sym":sym,"cur":cur,"cap":base})
            return False
    return True

def _cap_add(notional: float, sym: str) -> None:
    day = _yyyymmdd_now()
    if MAX_DAILY_NOTIONAL > 0:
        _inc_counter(f"cap:all:{day}", notional, ttl=48*3600)
    if MAX_DAILY_NOTIONAL_PER_SYMBOL > 0:
        _inc_counter(f"capn:{sym}:{day}", notional, ttl=48*3600)
    if MAX_DAILY_ALERTS > 0:
        _inc_counter(f"cnt:{sym}:{day}", 1, ttl=48*3600)
        _inc_counter(f"cnt:all:{day}", 1, ttl=48*3600)

# ================= Context =================
async def fetch_context_http(sym: str, interval: str = "15m") -> Optional[dict]:
    if not CONTEXT_URL:
        return None
    url = f"{CONTEXT_URL}?symbol={sym}&interval={interval}"
    headers = {"Authorization": f"Bearer {CONTEXT_TOKEN}"} if CONTEXT_TOKEN else {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        log.warning({"event":"context_http_fail","sym":sym,"err":str(e)})
    return None

async def fetch_context_batch_http(symbols: List[str], interval: str = "15m") -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    if not CONTEXT_BATCH_URL or not symbols:
        return out
    headers = {"Authorization": f"Bearer {CONTEXT_TOKEN}"} if CONTEXT_TOKEN else {}
    payload = {"symbols": symbols, "interval": interval, "compact": True}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(CONTEXT_BATCH_URL, json=payload, headers=headers)
            if r.status_code == 200:
                j = r.json() or {}
                for it in j.get("items", []):
                    s = it.get("symbol")
                    if s:
                        out[s.upper()] = it
    except Exception as e:
        log.warning({"event":"context_batch_fail","err":str(e)})
    return out

async def fetch_klines(sym: str, interval: str = "15m", limit: int = 200) -> Optional[List[List]]:
    url = f"{BINANCE_FUTURES_HTTP_BASE}/fapi/v1/klines"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params={"symbol": sym, "interval": interval, "limit": limit})
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        log.warning({"event":"klines_fail","sym":sym,"err":str(e)})
    return None

def try_f(x) -> Optional[float]:
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return None
        return float(x)
    except Exception:
        return None

def vol_regime_pct(df) -> str:
    try:
        atr = float(df["atr"].iloc[-1]); price = float(df["close"].iloc[-1])
        pct = (atr/price)*100.0 if price>0 else 0.0
        if pct < 1.2: return "low"
        if pct < 2.5: return "mid"
        return "high"
    except Exception:
        return "mid"

def danger_chop_flag(df) -> bool:
    try:
        adx = float(df["adx"].iloc[-1])
        mid = float(df["bb_mid"].iloc[-1]); up = float(df["bb_upper"].iloc[-1]); lo = float(df["bb_lower"].iloc[-1])
        price = float(df["close"].iloc[-1])
        width = ((up-lo)/mid) if mid>0 else 0.0
        near_mid = abs(price-mid)/mid if mid>0 else 0.0
        return (adx < 18) and (width < 0.025) and (near_mid < 0.005)
    except Exception:
        return False

async def make_compact_context(sym: str, interval: str = "15m") -> dict:
    data = await fetch_klines(sym, interval=interval, limit=200)
    if not data:
        return {"symbol": sym, "price": None, "ind": {}, "filters": {}}
    import pandas as pd
    cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(data, columns=cols[:len(data[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    base = prepare_indicators_for_backtest(df)
    row = base.iloc[-1]
    price = float(row["close"])
    return {
        "symbol": sym,
        "price": price,
        "ind": {
            "rsi": try_f(row.get("rsi")),
            "adx": try_f(row.get("adx")),
            "atr": try_f(row.get("atr")),
            "ema_21": try_f(row.get("ema_21")),
            "bb_mid": try_f(row.get("bb_mid")),
            "bb_upper": try_f(row.get("bb_upper")),
            "bb_lower": try_f(row.get("bb_lower")),
            "macd_hist": try_f(row.get("macd_hist")),
        },
        "filters": {"vol_regime": vol_regime_pct(base), "danger_chop": danger_chop_flag(base)}
    }

# ================= GPT =================
GPT_SYSTEM = (
    "You are a trading assistant. Respond ONLY as a strict JSON object "
    "with keys: trade_type(FUTURES/SPOT/GRID), side(LONG/SHORT), entry, sl, tp1, tp2, tp3, leverage(optional), "
    "budget_usd(optional), success_pct, rationale, anchor_alignment, time_to_tp1_m, time_to_tp2_m, time_to_tp3_m, time_to_sl_m."
)

def gpt_user_prompt(symbol: str, tz: str, ctx_str: str, modes: List[str]) -> str:
    return (
        f"Timezone={tz}\n"
        f"AllowedModes={','.join(modes)}\n"
        f"Context={ctx_str}\n"
        "Rules:\n"
        "- Provide ONE proposal only, matching AllowedModes and volatility regime.\n"
        "- Prefer precise limit entry; no chasing.\n"
        "- If volatility is high, prefer SPOT unless RR is excellent with wide stop.\n"
        "- success_pct must be realistic for the risk (usually 60–80).\n"
        "- If chop/danger, prefer GRID or SPOT; avoid high leverage.\n"
        "- Keep rationale short (<=25 words).\n"
        f"Symbol={symbol}\n"
        "Return JSON only."
    )

# ================= Gating / Prefs =================
def anchor_allows(side: str) -> bool:
    try:
        dec = evaluate_anchor(side, mode=ANCHOR_MODE if ANCHOR_MODE in ("off","soft","hard") else "soft")
        return bool(dec.allow)
    except Exception:
        return True

def rr_min_by_vol(base_min: float, vol_regime: str, is_spot: bool) -> float:
    # הידוק סף RR לפי תנודתיות
    if vol_regime == "high":
        return max(RR_HIGH, (SPOT_MIN_RR if is_spot else MIN_RR))
    if vol_regime == "mid":
        return max(RR_MID,  (SPOT_MIN_RR if is_spot else MIN_RR))
    return max(RR_LOW,  (SPOT_MIN_RR if is_spot else MIN_RR, base_min))

def entry_distance_ok(trade_type: str, entry: float, price: float, vol_regime: str) -> bool:
    if price <= 0 or entry <= 0:
        return False
    dist_pct = abs(entry - price) / price * 100.0
    if trade_type == "SPOT":
        if vol_regime == "high":  return dist_pct <= SPOT_HIGH_MAX_DIST
        if vol_regime == "mid":   return dist_pct <= SPOT_MID_MAX_DIST
        return dist_pct <= SPOT_LOW_MAX_DIST
    # FUTURES/GRID → נוקשה יותר על FUTURES
    if vol_regime == "high":  return dist_pct <= FUT_HIGH_MAX_DIST
    if vol_regime == "mid":   return dist_pct <= FUT_MID_MAX_DIST
    return dist_pct <= FUT_LOW_MAX_DIST

def type_gates_ok(sug: dict, prefs_min_rr: Optional[float], price: float, vol_regime: str) -> Tuple[bool, str]:
    t  = sug.get("trade_type")
    rr = rr_val(float(sug["entry"]), float(sug["sl"]), float(sug["tp1"]))
    is_spot = (t == "SPOT")
    # RR min לפי vol
    base = SPOT_MIN_RR if is_spot else MIN_RR
    local_min_rr = rr_min_by_vol(max(base, float(prefs_min_rr or 0.0)), vol_regime, is_spot)
    # אלסטיות בטוחה
    success_min = MIN_SUCCESS_PCT
    if rr >= ELITE_RR:
        success_min = max(50.0, MIN_SUCCESS_PCT - SUCCESS_DELTA_ON_ELITE)
    # בדיקות
    if rr < local_min_rr:
        return False, f"rr<{local_min_rr}"
    if float(sug.get("success_pct", 0.0)) < success_min:
        return False, f"success_pct<{success_min}"
    if not entry_distance_ok(t, float(sug["entry"]), price, vol_regime):
        return False, "entry_too_far_no_chase"
    if not anchor_allows(sug.get("side","LONG")):
        return False, "anchor_block"
    return True, "ok"

def apply_prefs(sug: dict, prefs: dict) -> dict:
    if prefs.get("modes"):
        allowed = set([m.upper() for m in prefs["modes"]])
        if sug.get("trade_type") not in allowed and allowed:
            sug["trade_type"] = list(allowed)[0]
    if sug.get("trade_type") == "FUTURES" and prefs.get("max_leverage"):
        try:
            lev = int(sug.get("leverage") or 0); mx = int(prefs["max_leverage"])
            if lev == 0 or lev > mx:
                sug["leverage"] = mx
        except Exception: pass
    if sug.get("trade_type") in ("FUTURES","SPOT") and prefs.get("budget_usd") and not sug.get("budget_usd"):
        try: sug["budget_usd"] = float(prefs["budget_usd"])
        except Exception: pass
    if sug.get("trade_type") == "GRID":
        if prefs.get("grid_levels") and not sug.get("grid_levels"):
            sug["grid_levels"] = prefs["grid_levels"]
        if prefs.get("grid_step_pct") and not sug.get("grid_step_pct"):
            sug["grid_step_pct"] = float(prefs["grid_step_pct"])
    return sug

def notional_guess(sug: dict, price: float) -> float:
    t = sug.get("trade_type")
    if t in ("FUTURES","SPOT"):
        if isinstance(sug.get("budget_usd"), (int,float)):
            return float(sug["budget_usd"])
        return 120.0
    return 90.0

# ================= OUT =================
async def post_alert(payload: dict) -> bool:
    body = json.dumps(payload, ensure_ascii=False).encode()
    headers = {"Content-Type":"application/json"}
    if OUTGOING_TOKEN:
        headers["Authorization"] = f"Bearer {OUTGOING_TOKEN}"
    if HMAC_SECRET:
        headers["X-Signature"] = _sign_hmac(body)
    headers["X-Idempotency-Key"] = _idem_key(payload)
    if not OUTGOING_WEBHOOK_URL:
        print("[DRY-RUN]", json.dumps(payload, ensure_ascii=False))
        return True
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.post(OUTGOING_WEBHOOK_URL, content=body, headers=headers)
            return r.status_code in (200,201,202)
    except Exception as e:
        print("ALERT POST ERR:", e)
    return False

# ================= CORE =================
async def run_symbol(sym: str, oai: Optional[AsyncOpenAI], ctx_pre: Optional[dict] = None, interval: str = "15m") -> Optional[dict]:
    global _SENT_THIS_SWEEP
    if _in_cooldown(sym):
        return None

    # context
    ctx = ctx_pre or await fetch_context_http(sym, interval=interval) or await make_compact_context(sym, interval=interval)
    price = float(ctx.get("price") or 0.0)
    if price <= 0:
        return None
    vol_regime = str(ctx.get("filters",{}).get("vol_regime","mid")).lower()

    prefs = get_symbol_prefs(sym)
    modes_allowed = SUGGEST_MODES.copy()
    if prefs.get("modes"):
        allow = set([m.upper() for m in prefs["modes"]])
        modes_allowed = [m for m in modes_allowed if m in allow] or SUGGEST_MODES

    ctx_str = json.dumps({"symbol": sym, "price": price, "ind": ctx.get("ind"), "filters": ctx.get("filters")}, separators=(",", ":"), ensure_ascii=False)
    pref_ctx_str = json.dumps({"symbol": sym, "hints": {
        "max_leverage": prefs.get("max_leverage"),
        "budget_usd": prefs.get("budget_usd"),
        "min_rr": prefs.get("min_rr"),
        "grid_levels": prefs.get("grid_levels"),
        "grid_step_pct": prefs.get("grid_step_pct"),
    }}, separators=(",", ":"), ensure_ascii=False)

    # GPT
    obj = None
    t0 = _now_ts()
    try:
        if oai:
            resp = await oai.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": GPT_SYSTEM},
                    {"role": "user",   "content": gpt_user_prompt(sym, TZ, ctx_str, modes_allowed) + "\n\nPrefs:\n" + pref_ctx_str},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            obj = json.loads(resp.choices[0].message.content)
        else:
            return None
    except Exception as e:
        log.warning({"event":"gpt_fail","sym":sym,"err":str(e)})
        return None
    finally:
        dur = _now_ts() - t0
        _LAT_SAMPLES.append(dur)
        if len(_LAT_SAMPLES) > 64:
            _LAT_SAMPLES.pop(0)

    sug = apply_prefs(obj, prefs)
    ok, why = type_gates_ok(sug, prefs.get("min_rr"), price, vol_regime)
    if not ok:
        log.info({"event":"gate_drop","sym":sym,"why":why})
        return None

    h = _dedup_key(sym, sug["side"], sug["trade_type"], float(sug["entry"]), float(sug["sl"]), float(sug["tp1"]), float(sug["tp2"]), float(sug["tp3"]), sug.get("leverage"))
    if _seen_dedup(h):
        log.info({"event":"dedup_drop","sym":sym})
        return None

    # per-symbol quality (for per-symbol caps)
    qs = None
    try:
        wl = load_watchlist()
        m = next((it for it in wl if it.get("symbol","").upper()==sym.upper()), None)
        if m and isinstance(m.get("quality_score"), int):
            qs = m["quality_score"]
    except Exception:
        qs = None

    notional = notional_guess(sug, price)
    if MAX_DAILY_ALERTS > 0 or MAX_DAILY_NOTIONAL > 0 or MAX_DAILY_NOTIONAL_PER_SYMBOL > 0:
        if not _cap_ok(notional, sym, qs):
            return None

    payload = {
        "type": "trade_proposal",
        "source": "gpt_auto_suggest",
        "symbol": sym,
        "interval": interval,
        "ts": int(_now_ts()),
        "tz": TZ,
        "proposal": sug,
        "context": {"price": price, "filters": ctx.get("filters")},
    }

    sent = await post_alert(payload)
    if sent:
        _touch_cooldown(sym)
        _mark_dedup(h)
        _cap_add(notional, sym)
        _SENT_THIS_SWEEP += 1
        return payload
    return None

async def load_symbol_pool(n: int) -> List[str]:
    if CORE_TOPK_URL:
        try:
            headers = {"Authorization": f"Bearer {CORE_TOPK_TOKEN}"} if CORE_TOPK_TOKEN else {}
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(CORE_TOPK_URL, headers=headers)
                if r.status_code == 200:
                    syms = (r.json().get("symbols") or [])
                    if syms: return [s.strip().upper() for s in syms][:n]
        except Exception as e:
            log.warning({"event":"topk_http_fail","err":str(e)})
    # fallback: בניה מקומית
    return build_symbol_pool(k=n, min_quality=6, include_anchor=True, include_shorts=True, balanced=True, explore_prob=0.2)

def _adaptive_boost() -> int:
    if len(_LAST_SWEEPS_SENT) < 3:
        return 0
    avg = sum(_LAST_SWEEPS_SENT[-3:]) / 3.0
    if avg < 1.0: return min(6, TOPK_MAX_BOOST)
    if avg < 2.0: return min(4, TOPK_MAX_BOOST)
    return 0

def _adapt_concurrency() -> int:
    global CUR_CONC
    p95 = _p95(_LAT_SAMPLES)
    if p95 <= 0:  # אין דגימות
        return CUR_CONC
    if p95 > GPT_P95_SLOW_S and CUR_CONC > OPENAI_CONC_MIN:
        CUR_CONC = max(OPENAI_CONC_MIN, CUR_CONC - 1)
    elif p95 < GPT_P95_FAST_S and CUR_CONC < OPENAI_CONC_MAX:
        CUR_CONC = min(OPENAI_CONC_MAX, CUR_CONC + 1)
    return CUR_CONC

async def main_loop():
    if not OPENAI_API_KEY:
        log.warning("OPENAI_API_KEY missing — worker idle (no GPT).")
    oai = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

    while True:
        start = _now_ts()
        global _SENT_THIS_SWEEP
        _SENT_THIS_SWEEP = 0

        try:
            boost = _adaptive_boost()
            local_topk = min(TOPK_PER_SWEEP + boost, TOPK_PER_SWEEP + TOPK_MAX_BOOST)
            symbols = await load_symbol_pool(local_topk)

            # Batch context (אופציונלי)
            ctx_map: Dict[str, dict] = {}
            if CONTEXT_BATCH_URL and symbols:
                batch = symbols[:CONTEXT_BATCH_Q]
                ctx_map = await fetch_context_batch_http(batch)

            # Adaptive concurrency
            conc = _adapt_concurrency()
            sem = asyncio.Semaphore(max(1, conc))
            log.info({"event":"sweep_start","count":len(symbols),"topk":local_topk,"boost":boost,"conc":conc})

            async def runner(sym: str):
                async with sem:
                    if _SENT_THIS_SWEEP >= SWEEP_CAP:
                        return
                    ctx_pre = ctx_map.get(sym) if ctx_map else None
                    if oai:
                        await run_symbol(sym, oai, ctx_pre=ctx_pre)
                    else:
                        # no GPT — idle
                        return

            await asyncio.gather(*[runner(s) for s in symbols])

            dur = _now_ts() - start
            _LAST_SWEEPS_SENT.append(_SENT_THIS_SWEEP)
            if len(_LAST_SWEEPS_SENT) > 5:
                _LAST_SWEEPS_SENT.pop(0)
            log.info({"event":"sweep_done","sent":_SENT_THIS_SWEEP,"t_sec":round(dur,2),"p95":round(_p95(_LAT_SAMPLES),2),"history":_LAST_SWEEPS_SENT})
        except Exception as e:
            log.error({"event":"sweep_error","err":str(e)})

        await asyncio.sleep(SUGGEST_INTERVAL_SECONDS)

if __name__ == "__main__":
    asyncio.run(main_loop())











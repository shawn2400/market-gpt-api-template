# workers/gpt_auto_suggest.py
from __future__ import annotations
import os, json, math, time, hmac, hashlib, base64, asyncio, logging, random
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

import httpx
from openai import AsyncOpenAI

from utils.indicators import prepare_indicators_for_backtest
from utils.watchlist_utils import build_symbol_pool, get_symbol_prefs
from utils.anchor import evaluate_anchor

# ====== ENV / CONFIG ======
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL     = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_MAX_CONC  = int(float(os.getenv("OPENAI_MAX_CONCURRENCY", "3")))  # ↑ כדי לאפשר יותר הצעות
OPENAI_TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))

SUGGEST_INTERVAL_SECONDS = int(float(os.getenv("SUGGEST_INTERVAL_SECONDS", "600")))
TOPK_PER_SWEEP           = int(float(os.getenv("TOPK_PER_SWEEP", "16")))  # ↑ ברירת מחדל 16
TOPK_MAX_BOOST           = int(float(os.getenv("TOPK_MAX_BOOST", "8")))   # הרחבה דינמית עד +8
SWEEP_CAP                = int(float(os.getenv("SWEEP_CAP", "999")))

# Gating
MIN_SUCCESS_PCT          = float(os.getenv("MIN_SUCCESS_PCT", "70"))
MIN_RR                   = float(os.getenv("MIN_RR", "1.8"))
SPOT_MIN_RR              = float(os.getenv("SPOT_MIN_RR", "1.5"))
ELITE_RR                 = float(os.getenv("ELITE_RR", "2.4"))            # RR גבוה מאוד
SUCCESS_DELTA_ON_ELITE   = float(os.getenv("SUCCESS_DELTA_ON_ELITE", "3"))# 70→67 מותר ל-Elite
ANCHOR_MODE              = os.getenv("ANCHOR_MODE", "soft").lower()

# Cooldown / De-dup
COOLDOWN_MINUTES = int(float(os.getenv("COOLDOWN_MINUTES", "30")))        # ↓ מעט כדי לאפשר יותר כמות
DEDUP_TTL_MIN    = int(float(os.getenv("DEDUP_TTL_MIN", "180")))

# Caps
MAX_DAILY_ALERTS              = int(float(os.getenv("MAX_DAILY_ALERTS", "0")))
MAX_DAILY_NOTIONAL            = float(os.getenv("MAX_DAILY_NOTIONAL", "0"))
MAX_DAILY_NOTIONAL_PER_SYMBOL = float(os.getenv("MAX_DAILY_NOTIONAL_PER_SYMBOL", "0"))

# Pool/Context
CORE_TOPK_URL    = os.getenv("CORE_TOPK_URL", "").strip()
CORE_TOPK_TOKEN  = os.getenv("CORE_TOPK_TOKEN", "").strip()
CONTEXT_URL      = os.getenv("CONTEXT_URL", "").strip()             # יחיד (fallback אם אין batch)
CONTEXT_TOKEN    = os.getenv("CONTEXT_TOKEN", "").strip()
CONTEXT_BATCH_URL= os.getenv("CONTEXT_BATCH_URL", "").strip()       # חדש: /context/batch (אופציונלי)
CONTEXT_BATCH_Q  = int(float(os.getenv("CONTEXT_BATCH_Q", "16")))   # כמה סמלים לבקש בבאץ'

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

# Redis (אופציונלי)
try:
    from utils.redis_client import redis_client as RED
except Exception:
    RED = None
USE_REDIS_LIMITS = bool(RED)

# Log
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gpt_auto_suggest")

# ====== STATE ======
_COOLDOWN: Dict[str, float] = {}
_DEDUP: Dict[str, float]    = {}
_DAILY: Dict[str, float]    = {}
_SENT_THIS_SWEEP = 0
_LAST_SWEEPS_SENT: List[int] = []  # היסטוריה קצרה לסוויפים (עד 3)

# ====== Utils ======
def _now_ts() -> float:
    return time.time()

def _yyyymmdd_now() -> str:
    dt = datetime.now(timezone.utc).astimezone()
    return dt.strftime("%Y%m%d")

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

def _idempotency_key(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]

def _cap_ok(notional: float, sym: str) -> bool:
    # all
    if MAX_DAILY_NOTIONAL > 0:
        key = f"cap:all:{_yyyymmdd_now()}"
        cur = _get_counter(key)
        if cur + notional > MAX_DAILY_NOTIONAL:
            log.info({"event":"cap_block_all","cur":cur,"ask":notional,"cap":MAX_DAILY_NOTIONAL})
            return False
    # per symbol
    if MAX_DAILY_NOTIONAL_PER_SYMBOL > 0:
        key = f"cap:{sym}:{_yyyymmdd_now()}"
        cur = _get_counter(key)
        if cur + notional > MAX_DAILY_NOTIONAL_PER_SYMBOL:
            log.info({"event":"cap_block_sym","sym":sym,"cur":cur,"ask":notional,"cap":MAX_DAILY_NOTIONAL_PER_SYMBOL})
            return False
    return True

def _cap_add(notional: float, sym: str) -> None:
    if MAX_DAILY_NOTIONAL > 0:
        _inc_counter(f"cap:all:{_yyyymmdd_now()}", notional)
    if MAX_DAILY_NOTIONAL_PER_SYMBOL > 0:
        _inc_counter(f"cap:{sym}:{_yyyymmdd_now()}", notional)

def _get_counter(key: str) -> float:
    if USE_REDIS_LIMITS:
        try:
            v = RED.get(key)
            return float(v or 0.0)
        except Exception:
            pass
    return _DAILY.get(key, 0.0)

def _inc_counter(key: str, val: float) -> None:
    if USE_REDIS_LIMITS:
        try:
            RED.incrbyfloat(key, float(val))
            return
        except Exception:
            pass
    _DAILY[key] = _DAILY.get(key, 0.0) + float(val)

def _dedup_key(sym: str, side: str, trade_type: str, entry: float, sl: float, tp1: float, tp2: float, tp3: float, lev: Optional[int]) -> str:
    raw = f"{sym}|{side}|{trade_type}|{entry:.8f}|{sl:.8f}|{tp1:.8f}|{tp2:.8f}|{tp3:.8f}|{lev or 0}"
    return hashlib.sha256(raw.encode()).hexdigest()

def _in_cooldown(sym: str) -> bool:
    if USE_REDIS_LIMITS:
        try:
            t = RED.get(f"cd:{sym}")
            if not t: return False
            return (_now_ts() - float(t)) < (COOLDOWN_MINUTES * 60)
        except Exception:
            pass
    last = _COOLDOWN.get(sym)
    return bool(last and (_now_ts() - last) < (COOLDOWN_MINUTES * 60))

def _touch_cooldown(sym: str) -> None:
    if USE_REDIS_LIMITS:
        try:
            RED.set(f"cd:{sym}", str(_now_ts()), ex=COOLDOWN_MINUTES*60)
            return
        except Exception:
            pass
    _COOLDOWN[sym] = _now_ts()

# ====== Context ======
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
    if not CONTEXT_BATCH_URL:
        return out
    headers = {"Authorization": f"Bearer {CONTEXT_TOKEN}"} if CONTEXT_TOKEN else {}
    payload = {"symbols": symbols, "interval": interval, "compact": True}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(CONTEXT_BATCH_URL, json=payload, headers=headers)
            if r.status_code == 200:
                j = r.json() or {}
                # מצופה {"ok":true,"items":[{"symbol":"BTCUSDT","price":...,"ind":...,"filters":...}, ...]}
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
        "filters": {
            "vol_regime": vol_regime_pct(base),
            "danger_chop": danger_chop_flag(base),
        }
    }

# ====== GPT ======
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

# ====== gating / prefs ======
def anchor_allows(side: str) -> bool:
    try:
        dec = evaluate_anchor(side, mode=ANCHOR_MODE if ANCHOR_MODE in ("off","soft","hard") else "soft")
        return bool(dec.allow)
    except Exception:
        return True

def type_gates_ok(sug: dict, prefs_min_rr: Optional[float]) -> Tuple[bool, str]:
    t = sug.get("trade_type")
    rr = rr_val(float(sug["entry"]), float(sug["sl"]), float(sug["tp1"]))
    base = SPOT_MIN_RR if t == "SPOT" else MIN_RR
    local_min_rr = max(base, float(prefs_min_rr or 0.0))

    # אלסטיות בטוחה: אם RR גבוה במיוחד → אפשר success מעט נמוך מהסף
    success = float(sug.get("success_pct", 0.0))
    success_min = MIN_SUCCESS_PCT
    if rr >= ELITE_RR:
        success_min = max(50.0, MIN_SUCCESS_PCT - SUCCESS_DELTA_ON_ELITE)

    if rr < local_min_rr:
        return False, f"rr<{local_min_rr}"
    if success < success_min:
        return False, f"success_pct<{success_min}"
    if not anchor_allows(sug.get("side","LONG")):
        return False, "anchor_block"
    return True, "ok"

def apply_prefs(sug: dict, prefs: dict) -> dict:
    if prefs.get("modes"):
        allowed = set([m.upper() for m in prefs["modes"]])
        if sug.get("trade_type") not in allowed:
            sug["trade_type"] = list(allowed)[0]
    if sug.get("trade_type") == "FUTURES" and prefs.get("max_leverage"):
        try:
            lev = int(sug.get("leverage") or 0)
            mx  = int(prefs["max_leverage"])
            if lev == 0 or lev > mx:
                sug["leverage"] = mx
        except Exception:
            pass
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
        return 120.0  # הערכה שמרנית מעט ↑
    return 90.0

# ====== OUT ======
async def post_alert(payload: dict) -> bool:
    body = json.dumps(payload, ensure_ascii=False).encode()
    headers = {"Content-Type":"application/json"}
    if OUTGOING_TOKEN:
        headers["Authorization"] = f"Bearer {OUTGOING_TOKEN}"
    if HMAC_SECRET:
        headers["X-Signature"] = _sign_hmac(body)
    headers["X-Idempotency-Key"] = _idempotency_key(payload)
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

# ====== CORE ======
async def run_symbol(sym: str, oai: AsyncOpenAI, ctx_pre: Optional[dict] = None, interval: str = "15m") -> Optional[dict]:
    global _SENT_THIS_SWEEP
    if _in_cooldown(sym):
        return None

    # context
    ctx = ctx_pre or await fetch_context_http(sym, interval=interval) or await make_compact_context(sym, interval=interval)
    price = float(ctx.get("price") or 0.0)
    if price <= 0:
        return None

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
    try:
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
    except Exception as e:
        log.warning({"event":"gpt_fail","sym":sym,"err":str(e)})
        return None

    sug = apply_prefs(obj, prefs)
    ok, why = type_gates_ok(sug, prefs.get("min_rr"))
    if not ok:
        log.info({"event":"gate_drop","sym":sym,"why":why})
        return None

    h = _dedup_key(sym, sug["side"], sug["trade_type"], float(sug["entry"]), float(sug["sl"]), float(sug["tp1"]), float(sug["tp2"]), float(sug["tp3"]), sug.get("leverage"))
    # De-dup (local/redis)
    if USE_REDIS_LIMITS:
        try:
            if RED.get(f"du:{h}"):
                log.info({"event":"dedup_drop","sym":sym})
                return None
        except Exception:
            pass
    else:
        ts_old = _DEDUP.get(h)
        if ts_old and (_now_ts() - ts_old) < (DEDUP_TTL_MIN * 60):
            log.info({"event":"dedup_drop","sym":sym})
            return None

    notional = notional_guess(sug, price)
    if MAX_DAILY_ALERTS > 0:
        cnt = _get_counter(f"cnt:all:{_yyyymmdd_now()}")
        if cnt >= MAX_DAILY_ALERTS:
            log.info({"event":"cap_alerts_drop"})
            return None
    if not _cap_ok(notional, sym):
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
        if USE_REDIS_LIMITS:
            try: RED.set(f"du:{h}", "1", ex=DEDUP_TTL_MIN*60)
            except Exception: pass
        else:
            _DEDUP[h] = _now_ts()
        if MAX_DAILY_ALERTS > 0:
            _inc_counter(f"cnt:all:{_yyyymmdd_now()}", 1)
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
    return build_symbol_pool(k=n, min_quality=6, include_anchor=True, include_shorts=True, balanced=True, explore_prob=0.2)

def _adaptive_boost() -> int:
    # אם 3 הסבבים האחרונים היו דלים (<2 בממוצע) – הגדל Top-K זמנית
    if len(_LAST_SWEEPS_SENT) < 3:
        return 0
    avg = sum(_LAST_SWEEPS_SENT[-3:]) / 3.0
    if avg < 2.0:
        return min(4, TOPK_MAX_BOOST)  # boost קטן וזהיר
    if avg < 1.0:
        return min(6, TOPK_MAX_BOOST)
    return 0

async def main_loop():
    if not OPENAI_API_KEY:
        log.warning("OPENAI_API_KEY missing — DRY mode (no GPT).")
    oai = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

    while True:
        start = _now_ts()
        global _SENT_THIS_SWEEP
        _SENT_THIS_SWEEP = 0

        try:
            # Adaptive expansion
            boost = _adaptive_boost()
            local_topk = min(TOPK_PER_SWEEP + boost, TOPK_PER_SWEEP + TOPK_MAX_BOOST)
            symbols = await load_symbol_pool(local_topk)
            log.info({"event":"sweep_start","count":len(symbols),"topk":local_topk,"boost":boost})

            # Batch context (אם יש)
            ctx_map: Dict[str, dict] = {}
            if CONTEXT_BATCH_URL and symbols:
                # חתוך למנות (ליתר בטחון)
                batch = symbols[:CONTEXT_BATCH_Q]
                ctx_map = await fetch_context_batch_http(batch)

            sem = asyncio.Semaphore(max(1, OPENAI_MAX_CONC))
            async def runner(sym: str):
                async with sem:
                    if _SENT_THIS_SWEEP >= SWEEP_CAP:
                        return
                    ctx_pre = ctx_map.get(sym) if ctx_map else None
                    if oai:
                        await run_symbol(sym, oai, ctx_pre=ctx_pre)
                    else:
                        # DRY: context מקומי
                        ctx = ctx_pre or await make_compact_context(sym)
                        print("[DRY-CONTEXT]", sym, json.dumps(ctx, ensure_ascii=False))

            await asyncio.gather(*[runner(s) for s in symbols])

            dur = _now_ts() - start
            _LAST_SWEEPS_SENT.append(_SENT_THIS_SWEEP)
            if len(_LAST_SWEEPS_SENT) > 5:
                _LAST_SWEEPS_SENT.pop(0)
            log.info({"event":"sweep_done","sent":_SENT_THIS_SWEEP,"t_sec":round(dur,2),"history":_LAST_SWEEPS_SENT})
        except Exception as e:
            log.error({"event":"sweep_error","err":str(e)})

        await asyncio.sleep(SUGGEST_INTERVAL_SECONDS)

if __name__ == "__main__":
    asyncio.run(main_loop())










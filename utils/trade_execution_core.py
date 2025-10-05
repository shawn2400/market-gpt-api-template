# utils/trade_execution_core.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, math, time, logging, json, hashlib
from typing import Optional, Dict, Any, List, Tuple
from contextlib import suppress  # ← נדרש כי משתמשים בו בהמשך

from utils.binance_client import (
    get_price, futures_mark_price, set_leverage, futures_create_order,
    get_symbol_filters, get_all_orders, futures_cancel_order, get_futures_client,
    futures_balance,
)

log = logging.getLogger("algogpt.trade_executor.core")

# ─────────── Policy & Defaults (ENV) ───────────
ALLOW_MARKET_ENTRY    = os.getenv("ALLOW_MARKET_ENTRY", "1").lower() in ("1","true","yes","on")
ENTRY_BAND_BPS        = float(os.getenv("ENTRY_BAND_BPS", "8.5"))
STOP_BAND_BPS         = float(os.getenv("STOP_BAND_BPS",  "10"))
ESCALATE_AFTER_S      = float(os.getenv("ESCALATE_AFTER_SEC", "10"))
ESCALATE_SLIP_BPS     = float(os.getenv("ESCALATE_SLIPPAGE_BPS", "15"))

# Guards
PERCENT_PRICE_GUARD_BPS = float(os.getenv("PERCENT_PRICE_GUARD_BPS", "45"))
SLIPPAGE_GUARD_BPS      = float(os.getenv("SLIPPAGE_GUARD_BPS", "35"))
POST_FILL_SANITY_BPS    = float(os.getenv("POST_FILL_SANITY_BPS", "40"))
ENFORCE_POST_FILL_SANITY = os.getenv("ENFORCE_POST_FILL_SANITY", "1").lower() in ("1","true","yes","on")

# Gate/Quality
QUALITY_DEFAULT       = float(os.getenv("QUALITY_DEFAULT", "6"))
MIN_QUALITY_SCORE     = float(os.getenv("MIN_QUALITY_SCORE", "7"))
MIN_QUALITY_FALLBACK  = float(os.getenv("MIN_QUALITY_FALLBACK", "6"))
MAX_ATR_PCT           = float(os.getenv("MAX_ATR_PCT", "2.5"))
MIN_VOLUME            = float(os.getenv("MIN_VOLUME", "0"))

# Enforce
ENFORCE_APPROVAL_ALWAYS  = os.getenv("ENFORCE_APPROVAL_ALWAYS", "1").lower() in ("1","true","yes","on")
REQUIRE_TP_AND_SL        = os.getenv("REQUIRE_TP_AND_SL", "1").lower() in ("1","true","yes","on")

# Ladder config
LADDER_TP_ENABLE          = os.getenv("LADDER_TP_ENABLE", "1").lower() in ("1","true","yes","on")
LADDER_TP_KIND            = os.getenv("LADDER_TP_KIND", "TAKE_PROFIT_MARKET").upper()
LADDER_TP_DEFAULT_PCTS    = os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5")
LADDER_TP_DEFAULT_SPLITS  = os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25")
LADDER_SL_ENABLE          = os.getenv("LADDER_SL_ENABLE", "1").lower() in ("1","true","yes","on")
LADDER_SL_DEFAULT_PCTS    = os.getenv("LADDER_SL_DEFAULT_PCTS", "0.8").strip()

# Dynamic SL / Trail
SL_DYNAMIC_ENABLE     = os.getenv("SL_DYNAMIC_ENABLE", "1").lower() in ("1","true","yes","on")
SL_ATR_MULT           = float(os.getenv("SL_ATR_MULT", "0.6"))

# Trail defaults (binance limits)
TRAIL_CALLBACK_MIN_PCT    = float(os.getenv("TRAIL_CALLBACK_MIN_PCT", "0.1"))
TRAIL_CALLBACK_MAX_PCT    = float(os.getenv("TRAIL_CALLBACK_MAX_PCT", "4.9"))

# Dynamic Budget & Leverage
BUDGET_DYNAMIC_ENABLE     = os.getenv("BUDGET_DYNAMIC_ENABLE", "1").lower() in ("1","true","yes","on")
BUDGET_USE_BALANCE        = os.getenv("BUDGET_USE_BALANCE", "1").lower() in ("1","true","yes","on")
BUDGET_DYNAMIC_RISK_PCTS  = os.getenv("BUDGET_DYNAMIC_RISK_PCTS", "1.5,3.0,5.0")

DYN_LEVERAGE_ENABLE       = os.getenv("DYN_LEVERAGE_ENABLE", "1").lower() in ("1","true","yes","on")
MIN_LEVERAGE              = int(float(os.getenv("MIN_LEVERAGE", "5")))
LEV_HARD_CAP              = int(float(os.getenv("LEV_HARD_CAP", "50")))
try:
    LEV_ADX_MAP_JSON      = json.loads(os.getenv("LEV_ADX_MAP_JSON", '{"30":15,"25":12,"20":9,"0":7}'))
except Exception:
    LEV_ADX_MAP_JSON      = {"30":15,"25":12,"20":9,"0":7}

# Backfill ENV defaults
DEFAULT_QTY_STEP      = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))
DEFAULT_TICK          = float(os.getenv("DEFAULT_PRICE_TICK", "0.01"))
DEFAULT_MIN_NOT       = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

ORDER_ID_PREFIX             = os.getenv("ORDER_ID_PREFIX", "").strip()
CANCEL_ONLY_PREFIXED_ORDERS = os.getenv("CANCEL_ONLY_PREFIXED_ORDERS", "0").lower() in ("1","true","yes","on")
CANCEL_PREFIX_OVERRIDE      = os.getenv("CANCEL_PREFIX_OVERRIDE", "").strip()

IDEMPOTENCY_TTL_SEC   = int(os.getenv("IDEMPOTENCY_TTL_SEC", "15"))

BOT_TOKEN           = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE            = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
CONFIRM_TTL_SEC     = int(os.getenv("CONFIRM_TTL_SEC", "180"))
TELEGRAM_CHAT_ID    = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")
TELEGRAM_PARSE_MODE = os.getenv("TELEGRAM_PARSE_MODE", "HTML").strip() or "HTML"

REDIS_URL = os.getenv("REDIS_URL", "").strip()
try:
    import redis  # type: ignore
    _redis_available = bool(REDIS_URL)
except Exception:
    _redis_available = False

try:
    LEVERAGE_SYMBOL_CAPS  = json.loads(os.getenv("LEVERAGE_SYMBOL_CAPS", '{"BTCUSDT":15,"1000PEPEUSDT":8}'))
except Exception:
    LEVERAGE_SYMBOL_CAPS  = {"BTCUSDT":15,"1000PEPEUSDT":8}

# ─────────── Quantize & math helpers ───────────
def _decimals(step_str: str) -> int:
    if "." not in step_str: return 0
    frac = step_str.split(".")[1].rstrip("0")
    return len(frac)

def _filters(symbol: str) -> Dict[str, Any]:
    try: return get_symbol_filters(symbol) or {}
    except Exception: return {}

def _q_price(symbol: str, price: float) -> Tuple[str, float]:
    f = _filters(symbol); tick = float(f.get("tickSize") or DEFAULT_TICK) or DEFAULT_TICK
    decs = _decimals(str(f.get("tickSize") or DEFAULT_TICK))
    steps = round(price / tick); p = steps * tick
    s = f"{p:.{decs}f}"; return s, float(s)

def _q_qty(symbol: str, qty: float) -> Tuple[str, float]:
    f = _filters(symbol); step = float(f.get("stepSize") or DEFAULT_QTY_STEP) or DEFAULT_QTY_STEP
    decs = _decimals(str(f.get("stepSize") or DEFAULT_QTY_STEP))
    steps = math.floor(max(0.0, qty) / step); q = max(step, steps * step)
    s = f"{q:.{decs}f}"; return s, float(s)

def _min_notional(symbol: str) -> float:
    f = _filters(symbol); mn = f.get("minNotional")
    try: return float(mn) if mn is not None else DEFAULT_MIN_NOT
    except Exception: return DEFAULT_MIN_NOT

def _ensure_min_notional(symbol: str, price: float, qty: float) -> float:
    mn = _min_notional(symbol)
    if price * qty >= mn: return qty
    need = mn / max(price, 1e-9)
    _, q2 = _q_qty(symbol, need); return q2

def _calc_qty(symbol: str, price: float, budget: Optional[float], leverage: int, quantity: Optional[float]) -> float:
    if quantity and quantity > 0:
        q = float(quantity)
    else:
        if not budget or budget <= 0:
            raise ValueError("Either positive budget or quantity must be provided")
        usd = float(budget) * float(leverage)
        q = usd / price
    q = _ensure_min_notional(symbol, price, q)
    _, q = _q_qty(symbol, q); return q

def _offset_bps(base: float, bps: float, sign: int) -> float:
    return base * (1.0 + sign * (bps / 10000.0))

# ─────────── Hedge / One-Way detection ───────────
_HEDGE_MODE_OVERRIDE = os.getenv("HEDGE_MODE", "").strip().lower()
_HEDGE_MODE_CACHE: Optional[bool] = None

def _is_hedge_mode_runtime() -> bool:
    global _HEDGE_MODE_CACHE
    if _HEDGE_MODE_OVERRIDE in ("1","true","yes","on","hedge"): return True
    if _HEDGE_MODE_OVERRIDE in ("0","false","no","off","oneway"): return False
    if _HEDGE_MODE_CACHE is not None: return _HEDGE_MODE_CACHE
    try:
        data = get_futures_client().futures_account()
        _HEDGE_MODE_CACHE = bool(data.get("dualSidePosition"))
    except Exception:
        _HEDGE_MODE_CACHE = False
    return _HEDGE_MODE_CACHE

def _effective_position_side(desired: str) -> str:
    desired = (desired or "BOTH").upper()
    if not _is_hedge_mode_runtime(): return "BOTH"
    return desired if desired in {"LONG","SHORT"} else "BOTH"

# ─────────── Indicators (ללא pandas) ───────────
def _ema(vals: List[float], period: int) -> List[float]:
    k = 2 / (period + 1); ema=[]; s=None
    for v in vals:
        s = v if s is None else (v*k + s*(1-k)); ema.append(s)
    return ema

def _atr_from_klines(kl: List[List[float]], period: int = 14) -> float:
    trs=[]; prev=None
    for r in kl:
        h=float(r[2]); l=float(r[3]); c=float(r[4])
        tr = (h-l) if prev is None else max(h-l, abs(h-prev), abs(l-prev))
        trs.append(tr); prev=c
    if len(trs) < period: return trs[-1] if trs else 0.0
    alpha = 1.0/period; s=None
    for v in trs:
        s = v if s is None else (alpha*v+(1-alpha)*s)
    return float(s or 0.0)

def _adx_from_klines(kl: List[List[float]], period: int = 14) -> float:
    if len(kl) < period + 2: return 0.0
    plus_dm, minus_dm, tr_list = [], [], []
    prev_h, prev_l, prev_c = None, None, None
    for r in kl:
        h, l, c = float(r[2]), float(r[3]), float(r[4])
        if prev_h is None:
            prev_h, prev_l, prev_c = h, l, c
            continue
        up_move   = h - prev_h
        down_move = prev_l - l
        pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
        mdm = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        plus_dm.append(pdm); minus_dm.append(mdm); tr_list.append(tr)

    def rma(xs: List[float], p: int) -> List[float]:
        alpha = 1/p; out=[]; s=None
        for x in xs:
            s = x if s is None else (alpha*x + (1-alpha)*s); out.append(s)
        return out

    if len(tr_list) < period: return 0.0
    tr_rma = rma(tr_list, period); pdm_rma = rma(plus_dm, period); mdm_rma = rma(minus_dm, period)
    dx=[]
    for t, p, m in zip(tr_rma, pdm_rma, mdm_rma):
        if t <= 0: di_p, di_m = 0.0, 0.0
        else:
            di_p = (p / t) * 100.0; di_m = (m / t) * 100.0
        denom = (di_p + di_m); dx.append(0.0 if denom == 0 else abs(di_p - di_m) / denom * 100.0)
    if not dx: return 0.0
    adx = rma(dx, period)[-1]; return float(adx or 0.0)

def _fetch_klines_raw(symbol: str, interval: str = "1m", limit: int = 60) -> List[List[float]]:
    cli = get_futures_client()
    data = cli.futures_klines(symbol=symbol.upper(), interval=interval, limit=min(1000, max(50, limit)))
    return data or []

def _quality_gate(symbol: str, side: str) -> Dict[str, Any]:
    try:
        kl = _fetch_klines_raw(symbol, "1m", 60)
        closes = [float(r[4]) for r in kl]
        vols   = [float(r[5]) for r in kl]
        if len(closes) < 30:
            return {"enter_ok": (QUALITY_DEFAULT >= MIN_QUALITY_SCORE), "score": QUALITY_DEFAULT, "reasons": ["insufficient_data"], "metrics": {}}

        ema21 = _ema(closes, 21)[-1]
        ema50 = _ema(closes, 50)[-1]
        last  = closes[-1]
        atr   = _atr_from_klines(kl, 14)
        atr_pct = (atr / last) * 100.0 if last > 0 else 999.0
        mom = (last / closes[-4] - 1.0) * 100.0

        trend_ok = (ema21 > ema50 and last > ema21) if side == "BUY" else (ema21 < ema50 and last < ema21)
        mom_ok   = (mom > 0.05) if side == "BUY" else (mom < -0.05)
        vol_ok   = True if MIN_VOLUME <= 0 else (vols[-1] >= MIN_VOLUME)
        atr_ok   = (atr_pct <= MAX_ATR_PCT)

        score = 0.0
        score += 4.0 if trend_ok else 0.0
        score += 3.0 if mom_ok else 0.0
        score += 2.0 if atr_ok else 0.0
        score += 1.0 if vol_ok else 0.0
        score = max(score, MIN_QUALITY_FALLBACK, QUALITY_DEFAULT)

        reasons=[]
        if not trend_ok: reasons.append("trend_mismatch")
        if not mom_ok:   reasons.append("weak_momentum")
        if not atr_ok:   reasons.append("atr_too_high")
        if not vol_ok:   reasons.append("low_volume")

        return {"enter_ok": score >= MIN_QUALITY_SCORE, "score": round(score, 2), "reasons": reasons,
                "metrics": {"ema21": ema21, "ema50": ema50, "atr_pct": atr_pct, "mom_pct": mom, "vol1m": vols[-1]}}
    except Exception as e:
        log.warning("quality gate failed: %s", e)
        return {"enter_ok": (QUALITY_DEFAULT >= MIN_QUALITY_SCORE), "score": QUALITY_DEFAULT, "reasons": ["gate_error"], "metrics": {}}

# ─────────── Budget & Leverage helpers ───────────
def _parse_csv_floats(s: str) -> List[float]:
    out: List[float] = []
    for x in (s or "").split(","):
        x = x.strip()
        if not x: continue
        try: out.append(float(x))
        except Exception: continue
    return out

def _parse_pct_csv(s: str) -> List[float]:
    return _parse_csv_floats(s)

def _balance_usdt() -> float:
    try:
        bal = futures_balance()
        for r in bal or []:
            if str(r.get("asset")).upper() == "USDT":
                av = r.get("availableBalance") or r.get("withdrawAvailable") or r.get("balance")
                return float(av)
    except Exception as e:
        log.warning("balance fetch failed: %s", e)
    return 0.0

def _choose_budget_dynamic(get_budget_usdt, quality: Optional[float], price: float) -> float:
    if not BUDGET_DYNAMIC_ENABLE:
        return get_budget_usdt(quality=quality, price=price)
    pcts = _parse_pct_csv(BUDGET_DYNAMIC_RISK_PCTS) or [1.5, 3.0, 5.0]
    pcts = (pcts + [pcts[-1]]*3)[:3]
    q = float(quality or QUALITY_DEFAULT)
    if q >= 9.5: pct = pcts[2]
    elif q >= 8.5: pct = pcts[1]
    elif q >= 7.0: pct = pcts[0]
    else:          pct = min(pcts[0], 1.0)

    if BUDGET_USE_BALANCE:
        bal = _balance_usdt()
        if bal <= 0:
            return get_budget_usdt(quality=quality, price=price)
        alloc = bal * (pct / 100.0)
        mn = _min_notional("BTCUSDT")
        return max(alloc, mn)
    return get_budget_usdt(quality=quality, price=price)

def _choose_leverage(symbol: str, adx: float, requested: int) -> int:
    lev = int(requested)
    if not DYN_LEVERAGE_ENABLE:
        return max(MIN_LEVERAGE, min(LEV_HARD_CAP, lev))
    try:
        pairs = sorted([(float(k), int(v)) for k, v in LEV_ADX_MAP_JSON.items()], key=lambda x: x[0])
    except Exception:
        pairs = [(0.0, 7), (20.0, 9), (25.0, 12), (30.0, 15)]
    dyn = MIN_LEVERAGE
    for thr, l in pairs:
        if adx >= thr: dyn = max(dyn, l)
    cap_by_symbol = int(LEVERAGE_SYMBOL_CAPS.get(symbol.upper(), LEV_HARD_CAP))
    dyn = max(MIN_LEVERAGE, min(dyn, cap_by_symbol, LEV_HARD_CAP))
    return max(MIN_LEVERAGE, min(max(lev, dyn), cap_by_symbol, LEV_HARD_CAP))

# ─────────── Idempotency (Redis/memory) ───────────
class _Idem:
    _mem: Dict[str, float] = {}
    _r = None
    try:
        if _redis_available:
            _r = redis.Redis.from_url(REDIS_URL, decode_responses=True)  # type: ignore
    except Exception as e:
        log.warning("Redis unavailable for idempotency: %s", e); _r = None

    @classmethod
    def _key(cls, payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        return f"idem:trade:{digest}"

    @classmethod
    def check_and_set(cls, payload: Dict[str, Any], ttl: int = IDEMPOTENCY_TTL_SEC) -> bool:
        k = cls._key(payload); now = time.time()
        if cls._r:
            try:
                ok = cls._r.set(k, str(int(now)), nx=True, ex=max(1, ttl))
                return bool(ok)
            except Exception as e:
                log.warning("Idempotency redis error: %s", e)
        ts = cls._mem.get(k, 0.0)
        if now - ts < ttl:
            return False
        cls._mem[k] = now
        for kk, vv in list(cls._mem.items()):
            if now - vv > ttl * 2:
                cls._mem.pop(kk, None)
        return True

# ─────────── Cancel old closing orders (TP/SL) ───────────
def _cancel_old_closing_orders(symbol: str) -> int:
    try:
        orders = get_all_orders(symbol, limit=50) or []
        tps = ("TAKE_PROFIT", "TAKE_PROFIT_MARKET")
        sls = ("STOP", "STOP_MARKET", "TRAILING_STOP_MARKET")
        pref = (CANCEL_PREFIX_OVERRIDE or ORDER_ID_PREFIX or "").strip()

        if CANCEL_ONLY_PREFIXED_ORDERS and not pref:
            log.warning("CANCEL_ONLY_PREFIXED_ORDERS=1 אך ללא prefix -> ביטול נחסם (0 orders).")
            return 0

        only_pref = bool(CANCEL_ONLY_PREFIXED_ORDERS and pref)
        count = 0
        for o in orders:
            st = (o.get("status") or "").upper()
            if st not in ("NEW","PARTIALLY_FILLED"):
                continue
            typ = (o.get("type") or "").upper()
            if typ not in tps + sls:
                continue
            if only_pref:
                coid = str(o.get("clientOrderId") or o.get("origClientOrderId") or "")
                if not coid.startswith(pref):
                    continue
            oid = o.get("orderId")
            if oid is None:
                continue
            try:
                futures_cancel_order(symbol, oid)
                count += 1
            except Exception as e:
                log.warning("cancel failed %s/%s: %s", symbol, oid, e)
        return count
    except Exception as e:
        log.warning("cancel_old_closing_orders error: %s", e)
        return 0

# ─────────── Ladder builders ───────────
def _build_ladders(sym: str, side: str, qty: float,
                   tp_targets: Optional[List[float]], tp_splits: Optional[List[float]],
                   sl_targets: Optional[List[float]], sl_splits: Optional[List[float]]) -> Dict[str, Any]:
    plan: Dict[str, Any] = {"tp_orders": [], "sl_orders": []}
    tp_kind_market = (LADDER_TP_KIND == "TAKE_PROFIT_MARKET")

    def _prep(kind: str, targets, splits=None):
        if not targets: return
        L = len(targets); w = list(splits) if splits else []
        if not w or len(w) != L: w = [1.0 / L] * L
        tot = sum(max(0.0, float(x)) for x in w) or 1.0
        remain = qty
        for i, (t, wi) in enumerate(zip(targets, w), start=1):
            alloc = qty * (wi / tot) if i < L else remain
            _, qalloc = _q_qty(sym, max(0.0, alloc))
            if qalloc <= 0: continue
            remain = max(0.0, remain - qalloc)
            _, stop_p = _q_price(sym, float(t))

            if kind == "TP":
                if tp_kind_market:
                    plan["tp_orders"].append({"type": "TAKE_PROFIT_MARKET","stopPrice": stop_p,"qty": qalloc})
                else:
                    plan["tp_orders"].append({"type": "TAKE_PROFIT","stopPrice": stop_p,"price": stop_p,"qty": qalloc})
            else:
                plan["sl_orders"].append({"type": "STOP_MARKET","stopPrice": stop_p,"qty": qalloc})

    if tp_targets: _prep("TP", tp_targets, tp_splits)
    if sl_targets: _prep("SL", sl_targets, sl_splits)
    return plan

def _normalize_position_side(ps: Optional[str]) -> str:
    ps = (ps or "BOTH").upper().strip()
    return ps if ps in {"BOTH", "LONG", "SHORT"} else "BOTH"

def _close_side_for(entry_side: str) -> str:
    return "SELL" if entry_side.upper() == "BUY" else "BUY"

def _pos_side_for_entry(side: str) -> str:
    return "LONG" if side.upper() == "BUY" else "SHORT"

def _normalize_entry_side(side: str) -> str:
    s = (side or "").upper().strip()
    if s in ("BUY","LONG"):  return "BUY"
    if s in ("SELL","SHORT"): return "SELL"
    raise ValueError("side must be BUY/SELL or LONG/SHORT")

def _compute_tp_sl_targets(side: str, anchor: float, kl: Optional[List[List[float]]]) -> Tuple[Optional[List[float]], Optional[List[float]], Optional[List[float]]]:
    tp_targets: Optional[List[float]] = None
    tp_splits : Optional[List[float]] = None
    sl_targets: Optional[List[float]] = None

    if LADDER_TP_ENABLE:
        with suppress(Exception):
            tps = [float(x) for x in _parse_csv_floats(LADDER_TP_DEFAULT_PCTS)]
            sign = +1 if side=="BUY" else -1
            tp_targets = [anchor * (1.0 + sign * p/100.0) for p in tps]
            tp_splits = [float(x) for x in _parse_csv_floats(LADDER_TP_DEFAULT_SPLITS)] or None

    if SL_DYNAMIC_ENABLE and kl:
        with suppress(Exception):
            atr = _atr_from_klines(kl, 14)
            sign = -1 if side=="BUY" else +1
            sl_p = anchor * (1.0 + sign * ((atr / max(anchor, 1e-9)) * SL_ATR_MULT * 100.0) / 100.0)
            sl_targets = [sl_p]

    if (not sl_targets) and LADDER_SL_ENABLE:
        with suppress(Exception):
            src = LADDER_SL_DEFAULT_PCTS if LADDER_SL_DEFAULT_PCTS else "0.8"
            slps = [float(x) for x in _parse_csv_floats(src)]
            sign = -1 if side=="BUY" else +1
            sl_targets = [anchor * (1.0 + sign * p/100.0) for p in slps]

    return tp_targets, tp_splits, sl_targets

def _compute_trailing_callback_pct(anchor_price: float, atr: Optional[float], mult: float) -> Optional[float]:
    if not (atr and anchor_price > 0 and mult > 0):
        return None
    raw_pct = (atr * mult) / anchor_price * 100.0
    clamped = max(TRAIL_CALLBACK_MIN_PCT, min(TRAIL_CALLBACK_MAX_PCT, raw_pct))
    if abs(clamped - raw_pct) > 1e-9:
        log.info("trail.callbackRate clamped: raw=%.4f%% -> used=%.4f%% (limits %.2f–%.2f%%)",
                 raw_pct, clamped, TRAIL_CALLBACK_MIN_PCT, TRAIL_CALLBACK_MAX_PCT)
    return clamped

__all__ = [
    # env & constants
    "ALLOW_MARKET_ENTRY","ENTRY_BAND_BPS","STOP_BAND_BPS","ESCALATE_AFTER_S","ESCALATE_SLIP_BPS",
    "PERCENT_PRICE_GUARD_BPS","SLIPPAGE_GUARD_BPS","POST_FILL_SANITY_BPS","ENFORCE_POST_FILL_SANITY",
    "QUALITY_DEFAULT","MIN_QUALITY_SCORE","MIN_QUALITY_FALLBACK","MAX_ATR_PCT","MIN_VOLUME",
    "ENFORCE_APPROVAL_ALWAYS","REQUIRE_TP_AND_SL",
    "LADDER_TP_ENABLE","LADDER_TP_KIND","LADDER_TP_DEFAULT_PCTS","LADDER_TP_DEFAULT_SPLITS",
    "LADDER_SL_ENABLE","LADDER_SL_DEFAULT_PCTS",
    "TRAIL_CALLBACK_MIN_PCT","TRAIL_CALLBACK_MAX_PCT",
    "BUDGET_DYNAMIC_ENABLE","BUDGET_USE_BALANCE","BUDGET_DYNAMIC_RISK_PCTS",
    "DYN_LEVERAGE_ENABLE","MIN_LEVERAGE","LEV_HARD_CAP","LEV_ADX_MAP_JSON",
    "ORDER_ID_PREFIX","CANCEL_ONLY_PREFIXED_ORDERS","CANCEL_PREFIX_OVERRIDE",
    "IDEMPOTENCY_TTL_SEC","BOT_TOKEN","API_BASE","CONFIRM_TTL_SEC","TELEGRAM_CHAT_ID","TELEGRAM_PARSE_MODE",
    # helpers
    "_q_p










































































































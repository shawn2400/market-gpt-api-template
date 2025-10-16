# -*- coding: utf-8 -*-
from __future__ import annotations
import os, math, time, logging, json, hashlib
from typing import Optional, Dict, Any, List
from utils.binance_client import get_symbol_filters, get_all_orders, futures_cancel_order, get_futures_client, futures_balance

log = logging.getLogger("algogpt.trade_executor.core")

ALLOW_MARKET_ENTRY = os.getenv("ALLOW_MARKET_ENTRY", "1").lower() in ("1","true","yes","on")
ENTRY_BAND_BPS = float(os.getenv("ENTRY_BAND_BPS", "8.5"))
STOP_BAND_BPS = float(os.getenv("STOP_BAND_BPS", "10"))
ESCALATE_AFTER_S = float(os.getenv("ESCALATE_AFTER_SEC", "10"))
ESCALATE_SLIP_BPS = float(os.getenv("ESCALATE_SLIPPAGE_BPS", "15"))
PERCENT_PRICE_GUARD_BPS = float(os.getenv("PERCENT_PRICE_GUARD_BPS", "45"))
SLIPPAGE_GUARD_BPS = float(os.getenv("SLIPPAGE_GUARD_BPS", "35"))
POST_FILL_SANITY_BPS = float(os.getenv("POST_FILL_SANITY_BPS", "40"))
ENFORCE_POST_FILL_SANITY = os.getenv("ENFORCE_POST_FILL_SANITY", "1").lower() in ("1","true","yes","on")
QUALITY_DEFAULT = float(os.getenv("QUALITY_DEFAULT", "6"))
MIN_QUALITY_SCORE = float(os.getenv("MIN_QUALITY_SCORE", "7"))
MIN_QUALITY_FALLBACK = float(os.getenv("MIN_QUALITY_FALLBACK", "6"))
MAX_ATR_PCT = float(os.getenv("MAX_ATR_PCT", "2.5"))
MIN_VOLUME = float(os.getenv("MIN_VOLUME", "0"))
ENFORCE_APPROVAL_ALWAYS = os.getenv("ENFORCE_APPROVAL_ALWAYS", "1").lower() in ("1","true","yes","on")
REQUIRE_TP_AND_SL = os.getenv("REQUIRE_TP_AND_SL", "1").lower() in ("1","true","yes","on")
LADDER_TP_ENABLE = os.getenv("LADDER_TP_ENABLE", "1").lower() in ("1","true","yes","on")
LADDER_TP_KIND = os.getenv("LADDER_TP_KIND", "TAKE_PROFIT_MARKET").upper()
LADDER_TP_DEFAULT_PCTS = os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5")
LADDER_TP_DEFAULT_SPLITS = os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25")
LADDER_SL_ENABLE = os.getenv("LADDER_SL_ENABLE", "1").lower() in ("1","true","yes","on")
LADDER_SL_DEFAULT_PCTS = os.getenv("LADDER_SL_DEFAULT_PCTS", "0.8").strip()
TRAIL_CALLBACK_MIN_PCT = float(os.getenv("TRAIL_CALLBACK_MIN_PCT", "0.1"))
TRAIL_CALLBACK_MAX_PCT = float(os.getenv("TRAIL_CALLBACK_MAX_PCT", "4.9"))
BUDGET_DYNAMIC_ENABLE = os.getenv("BUDGET_DYNAMIC_ENABLE", "1").lower() in ("1","true","yes","on")
BUDGET_USE_BALANCE = os.getenv("BUDGET_USE_BALANCE", "1").lower() in ("1","true","yes","on")
BUDGET_DYNAMIC_RISK_PCTS = os.getenv("BUDGET_DYNAMIC_RISK_PCTS", "1.5,3.0,5.0")
DYN_LEVERAGE_ENABLE = os.getenv("DYN_LEVERAGE_ENABLE", "1").lower() in ("1","true","yes","on")
MIN_LEVERAGE = int(float(os.getenv("MIN_LEVERAGE", "5")))
LEV_HARD_CAP = int(float(os.getenv("LEV_HARD_CAP", "50")))
try:
    LEV_ADX_MAP_JSON = json.loads(os.getenv("LEV_ADX_MAP_JSON", '{"30":15,"25":12,"20":9,"0":7}'))
except Exception:
    LEV_ADX_MAP_JSON = {"30":15,"25":12,"20":9,"0":7}
DEFAULT_QTY_STEP = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))
DEFAULT_TICK = float(os.getenv("DEFAULT_PRICE_TICK", "0.01"))
DEFAULT_MIN_NOT = float(os.getenv("MIN_NOTIONAL_USDT", "5"))
ORDER_ID_PREFIX = os.getenv("ORDER_ID_PREFIX", "").strip()
CANCEL_ONLY_PREFIXED_ORDERS = os.getenv("CANCEL_ONLY_PREFIXED_ORDERS", "0").lower() in ("1","true","yes","on")
CANCEL_PREFIX_OVERRIDE = os.getenv("CANCEL_PREFIX_OVERRIDE", "").strip()
IDEMPOTENCY_TTL_SEC = int(os.getenv("IDEMPOTENCY_TTL_SEC", "15"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
CONFIRM_TTL_SEC = int(os.getenv("CONFIRM_TTL_SEC", "180"))
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")
TELEGRAM_PARSE_MODE = os.getenv("TELEGRAM_PARSE_MODE", "HTML").strip() or "HTML"
REDIS_URL = os.getenv("REDIS_URL", "").strip()
try:
    import redis
    _redis_available = bool(REDIS_URL)
except Exception:
    _redis_available = False
try:
    LEVERAGE_SYMBOL_CAPS = json.loads(os.getenv("LEVERAGE_SYMBOL_CAPS", '{"BTCUSDT":15,"1000PEPEUSDT":8}'))
except Exception:
    LEVERAGE_SYMBOL_CAPS = {"BTCUSDT":15,"1000PEPEUSDT":8}
_HEDGE_MODE_OVERRIDE = os.getenv("HEDGE_MODE", "").strip().lower()
_HEDGE_MODE_CACHE: Optional[bool] = None

def _decimals(step_str: str) -> int:
    if "." not in step_str:
        return 0
    frac = step_str.split(".")[1].rstrip("0")
    return len(frac)

def _filters(symbol: str) -> Dict[str, Any]:
    try:
        return get_symbol_filters(symbol) or {}
    except Exception:
        return {}

def _q_price(symbol: str, price: float) -> str:
    f = _filters(symbol)
    tick = float(f.get("tickSize") or DEFAULT_TICK) or DEFAULT_TICK
    decs = _decimals(str(f.get("tickSize") or DEFAULT_TICK))
    steps = round(price / tick)
    p = steps * tick
    return f"{p:.{decs}f}"

def _q_qty(symbol: str, qty: float) -> str:
    f = _filters(symbol)
    step = float(f.get("stepSize") or DEFAULT_QTY_STEP) or DEFAULT_QTY_STEP
    decs = _decimals(str(f.get("stepSize") or DEFAULT_QTY_STEP))
    steps = math.floor(max(0.0, qty) / step)
    q = max(step, steps * step)
    return f"{q:.{decs}f}"

def _min_notional(symbol: str) -> float:
    f = _filters(symbol)
    mn = f.get("minNotional")
    try:
        return float(mn) if mn is not None else DEFAULT_MIN_NOT
    except Exception:
        return DEFAULT_MIN_NOT

def _ensure_min_notional(symbol: str, price: float, qty_str: str) -> str:
    try:
        qf = float(qty_str)
    except Exception:
        qf = 0.0
    mn = _min_notional(symbol)
    if price * qf >= mn:
        return qty_str
    need = mn / max(price, 1e-9)
    return _q_qty(symbol, need)

def _calc_qty(symbol: str, price: float, budget: Optional[float], leverage: int, quantity: Optional[float]) -> float:
    if quantity and quantity > 0:
        q = float(quantity)
    else:
        if not budget or budget <= 0:
            raise ValueError("Either positive budget or quantity must be provided")
        usd = float(budget) * float(leverage)
        q = usd / price
    q = float(_ensure_min_notional(symbol, price, _q_qty(symbol, q)))
    return q

def _offset_bps(base: float, bps: float) -> float:
    return base * (1.0 + (bps / 10000.0))

def _is_hedge_mode_runtime() -> bool:
    global _HEDGE_MODE_CACHE
    if _HEDGE_MODE_OVERRIDE in ("1","true","yes","on","hedge"):
        return True
    if _HEDGE_MODE_OVERRIDE in ("0","false","no","off","oneway"):
        return False
    if _HEDGE_MODE_CACHE is not None:
        return _HEDGE_MODE_CACHE
    try:
        data = get_futures_client().futures_account()
        _HEDGE_MODE_CACHE = bool(data.get("dualSidePosition"))
    except Exception:
        _HEDGE_MODE_CACHE = False
    return _HEDGE_MODE_CACHE

def _effective_position_side(desired: str, hedge_runtime: Optional[bool]=None) -> str:
    d = (desired or "BOTH").upper()
    if hedge_runtime is None:
        hedge_runtime = _is_hedge_mode_runtime()
    if not hedge_runtime:
        return "BOTH"
    return d if d in {"LONG","SHORT"} else "BOTH"

def _ema(vals: List[float], period: int) -> List[float]:
    k = 2 / (period + 1)
    ema: List[float] = []
    s: Optional[float] = None
    for v in vals:
        s = v if s is None else (v * k + s * (1 - k))
        ema.append(s)
    return ema

def _atr_from_klines(kl: List[List[float]], period: int = 14) -> float:
    trs: List[float] = []
    prev: Optional[float] = None
    for r in kl:
        h = float(r[2]); l = float(r[3]); c = float(r[4])
        tr = (h - l) if prev is None else max(h - l, abs(h - prev), abs(l - prev))
        trs.append(tr); prev = c
    if len(trs) < period:
        return trs[-1] if trs else 0.0
    alpha = 1.0 / period
    s: Optional[float] = None
    for v in trs:
        s = v if s is None else (alpha * v + (1 - alpha) * s)
    return float(s or 0.0)

def _adx_from_klines(kl: List[List[float]], period: int = 14) -> float:
    if len(kl) < period + 2:
        return 0.0
    plus_dm: List[float] = []
    minus_dm: List[float] = []
    tr_list: List[float] = []
    prev_h = prev_l = prev_c = None
    for r in kl:
        h, l, c = float(r[2]), float(r[3]), float(r[4])
        if prev_h is None:
            prev_h, prev_l, prev_c = h, l, c
            continue
        up_move = h - prev_h
        down_move = prev_l - l
        pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
        mdm = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        plus_dm.append(pdm); minus_dm.append(mdm); tr_list.append(tr)
    def rma(xs: List[float], p: int) -> List[float]:
        alpha = 1 / p
        out: List[float] = []
        s: Optional[float] = None
        for x in xs:
            s = x if s is None else (alpha * x + (1 - alpha) * s)
            out.append(s)
        return out
    if len(tr_list) < period:
        return 0.0
    tr_rma = rma(tr_list, period); pdm_rma = rma(plus_dm, period); mdm_rma = rma(minus_dm, period)
    dx: List[float] = []
    for t, p, m in zip(tr_rma, pdm_rma, mdm_rma):
        if t <= 0:
            di_p, di_m = 0.0, 0.0
        else:
            di_p = (p / t) * 100.0
            di_m = (m / t) * 100.0
        denom = (di_p + di_m)
        dx.append(0.0 if denom == 0 else abs(di_p - di_m) / denom * 100.0)
    if not dx:
        return 0.0
    adx = rma(dx, period)[-1]
    return float(adx or 0.0)

def _fetch_klines_raw(symbol: str, interval: str = "1m", limit: int = 60) -> List[List[float]]:
    cli = get_futures_client()
    data = cli.futures_klines(symbol=symbol.upper(), interval=interval, limit=min(1000, max(50, limit)))
    return data or []

def _parse_csv_floats(s: str) -> List[float]:
    out: List[float] = []
    for x in (s or "").split(","):
        x = x.strip()
        if not x:
            continue
        try:
            out.append(float(x))
        except Exception:
            continue
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
    except Exception:
        pass
    return 0.0

def _choose_budget_dynamic(get_budget_usdt, quality: Optional[float], price: float, symbol: Optional[str]=None) -> float:
    if not BUDGET_DYNAMIC_ENABLE:
        return get_budget_usdt(quality=quality, price=price)
    pcts = _parse_pct_csv(BUDGET_DYNAMIC_RISK_PCTS) or [1.5, 3.0, 5.0]
    pcts = (pcts + [pcts[-1]]*3)[:3]
    q = float(quality or QUALITY_DEFAULT)
    if q >= 9.5: pct = pcts[2]
    elif q >= 8.5: pct = pcts[1]
    elif q >= 7.0: pct = pcts[0]
    else: pct = min(pcts[0], 1.0)
    if BUDGET_USE_BALANCE:
        bal = _balance_usdt()
        if bal <= 0:
            return get_budget_usdt(quality=quality, price=price)
        alloc = bal * (pct / 100.0)
        mn = _min_notional((symbol or "BTCUSDT"))
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
        if adx >= thr:
            dyn = max(dyn, l)
    cap_by_symbol = int(LEVERAGE_SYMBOL_CAPS.get(symbol.upper(), LEV_HARD_CAP))
    dyn = max(MIN_LEVERAGE, min(dyn, cap_by_symbol, LEV_HARD_CAP))
    return max(MIN_LEVERAGE, min(max(lev, dyn), cap_by_symbol, LEV_HARD_CAP))

class _Idem:
    def __init__(self, prefix: str="idem", ttl: int=IDEMPOTENCY_TTL_SEC):
        self.prefix = prefix
        self.ttl = max(1, int(ttl))
        self._mem: Dict[str, float] = {}
        self._r = None
        try:
            if _redis_available:
                self._r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        except Exception:
            self._r = None
    def _key(self, payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        return f"{self.prefix}:{digest}"
    def check_and_set(self, payload: Dict[str, Any]) -> bool:
        k = self._key(payload); now = time.time()
        if self._r:
            try:
                ok = self._r.set(k, str(int(now)), nx=True, ex=self.ttl)
                return bool(ok)
            except Exception:
                pass
        ts = self._mem.get(k, 0.0)
        if now - ts < self.ttl:
            return False
        self._mem[k] = now
        for kk, vv in list(self._mem.items()):
            if now - vv > self.ttl * 2:
                self._mem.pop(kk, None)
        return True

def _cancel_old_closing_orders(symbol: str, position_side: Optional[str]=None, kinds: Optional[tuple]=None) -> int:
    try:
        orders = get_all_orders(symbol, limit=50) or []
        tps = ("TAKE_PROFIT", "TAKE_PROFIT_MARKET")
        sls = ("STOP", "STOP_MARKET", "TRAILING_STOP_MARKET")
        target_kinds = kinds or (tps + sls)
        pref = (CANCEL_PREFIX_OVERRIDE or ORDER_ID_PREFIX or "").strip()
        if CANCEL_ONLY_PREFIXED_ORDERS and not pref:
            return 0
        only_pref = bool(CANCEL_ONLY_PREFIXED_ORDERS and pref)
        count = 0
        ps_norm = (position_side or "").upper().strip()
        for o in orders:
            st = (o.get("status") or "").upper()
            if st not in ("NEW","PARTIALLY_FILLED"):
                continue
            typ = (o.get("type") or "").upper()
            if typ not in target_kinds:
                continue
            if ps_norm and (o.get("positionSide","").upper() != ps_norm):
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
            except Exception:
                pass
        return count
    except Exception:
        return 0

def _normalize_position_side(ps: Optional[str]) -> str:
    ps = (ps or "BOTH").upper().strip()
    return ps if ps in {"BOTH","LONG","SHORT"} else "BOTH"

def _close_side_for(entry_side: str) -> str:
    return "SELL" if entry_side.upper() == "BUY" else "BUY"

def _pos_side_for_entry(side: str) -> str:
    return "LONG" if side.upper() == "BUY" else "SHORT"

def _normalize_entry_side(side: str) -> str:
    s = (side or "").upper().strip()
    if s in ("BUY","LONG"):
        return "BUY"
    if s in ("SELL","SHORT"):
        return "SELL"
    raise ValueError("side must be BUY/SELL or LONG/SHORT")

def _compute_tp_sl_targets(symbol: str, side: str, qty: float, price_ref: float, plan: Dict[str,Any], ladder_tp_enable: bool, ladder_tp_kind: str, ladder_tp_default_pcts: str, ladder_tp_default_splits: str, ladder_sl_enable: bool, ladder_sl_default_pcts: str, sl_dynamic_enable: bool, sl_atr_mult: float, atr_abs: Optional[float], stop_band_bps: float) -> Dict[str, Any]:
    out: Dict[str, Any] = {"tp": [], "sl": None}
    if ladder_tp_enable:
        try:
            pcts = _parse_csv_floats(ladder_tp_default_pcts)
            splits = _parse_csv_floats(ladder_tp_default_splits)
            if not splits or len(splits) != len(pcts):
                splits = [1.0/len(pcts)]*len(pcts) if pcts else []
            sign = +1 if side.upper()=="BUY" else -1
            remain = qty
            for i, (pct, w) in enumerate(zip(pcts, splits), start=1):
                target = price_ref * (1.0 + sign * pct/100.0)
                alloc = qty * w if i < len(pcts) else remain
                alloc = max(0.0, alloc)
                q_str = _q_qty(symbol, alloc)
                qf = float(q_str)
                remain = max(0.0, remain - qf)
                if qf > 0:
                    out["tp"].append({"price": float(_q_price(symbol, target)), "qty": qf})
        except Exception:
            pass
    sl_given = plan.get("sl") or None
    if sl_given and isinstance(sl_given, dict) and float(sl_given.get("price", 0.0)) > 0:
        out["sl"] = {"price": float(sl_given["price"]), "qty": float(sl_given.get("qty", qty))}
    elif ladder_sl_enable:
        try:
            src = ladder_sl_default_pcts if ladder_sl_default_pcts else "0.8"
            slps = _parse_csv_floats(src)
            if slps:
                pct = float(slps[0])
                sign = -1 if side.upper()=="BUY" else +1
                slp = price_ref * (1.0 + sign * pct/100.0)
                out["sl"] = {"price": float(_q_price(symbol, slp)), "qty": float(_q_qty(symbol, qty))}
        except Exception:
            pass
    if (out["sl"] is None) and sl_dynamic_enable and atr_abs and atr_abs > 0:
        if side.upper()=="BUY":
            slp = max(1e-12, price_ref - sl_atr_mult * atr_abs)
        else:
            slp = max(1e-12, price_ref + sl_atr_mult * atr_abs)
        out["sl"] = {"price": float(_q_price(symbol, slp)), "qty": float(_q_qty(symbol, qty))}
    return out

def _compute_trailing_callback_pct(plan: Dict[str,Any], atr_abs: Optional[float], min_pct: float, max_pct: float, default_mult: float) -> Optional[float]:
    if not atr_abs:
        return None
    price_ref = float(plan.get("entry_price") or plan.get("price") or 0.0) or 0.0
    if price_ref <= 0:
        return None
    raw_pct = (atr_abs * default_mult) / price_ref * 100.0
    return max(min_pct, min(max_pct, raw_pct))

def _quality_gate(quality: Optional[float], min_score: float, atr_pct: Optional[float], atr_abs: Optional[float], max_atr_pct: float, volume: Optional[float], min_volume: float) -> (bool, str):
    q = float(quality if quality is not None else QUALITY_DEFAULT)
    if q < (min_score if min_score > 0 else MIN_QUALITY_FALLBACK):
        return False, "quality_below_min"
    if atr_pct is not None and atr_pct > max_atr_pct:
        return False, "atr_pct_too_high"
    if volume is not None and min_volume > 0 and volume < min_volume:
        return False, "low_volume"
    return True, ""

__all__ = [
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
    "_q_price","_q_qty","_ensure_min_notional","_calc_qty","_offset_bps",
    "_is_hedge_mode_runtime","_effective_position_side",
    "_fetch_klines_raw","_adx_from_klines","_atr_from_klines","_quality_gate",
    "_choose_budget_dynamic","_choose_leverage","_parse_csv_floats",
    "_cancel_old_closing_orders","_normalize_position_side",
    "_close_side_for","_pos_side_for_entry","_normalize_entry_side",
    "_compute_tp_sl_targets","_compute_trailing_callback_pct",
    "_Idem",
]













































































































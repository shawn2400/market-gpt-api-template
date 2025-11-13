# utils/auto_executor.py
from __future__ import annotations
import os, math, time, logging, asyncio, json, hashlib
from typing import Optional, Dict, Any, List, Tuple

import httpx

from utils.binance_client import (
    get_price, futures_mark_price, set_leverage, futures_create_order,
    get_symbol_filters, get_all_orders, futures_cancel_order, get_futures_client
)

# ✅ Dynamic budget (תאימות לשמות שונים במודול התקציב)
try:
    from utils.budget import get_budget_usdt as _get_budget
except Exception:
    try:
        from utils.budget import get_trade_budget_usdt as _get_budget  # type: ignore
    except Exception:
        def _get_budget(symbol: Optional[str] = None, *, quality: Optional[float] = None,
                        atr: Optional[float] = None, price: Optional[float] = None) -> float:  # type: ignore
            try:
                return float(os.getenv("MAX_TRADE_BUDGET", "100"))
            except Exception:
                return 100.0

# ✅ Risk (אופציונלי)
try:
    from utils.risk_checker import pre_trade_risk_check, RISK_CHECK_ENABLE
except Exception:
    RISK_CHECK_ENABLE = False
    def pre_trade_risk_check(*args, **kwargs):  # type: ignore
        return {"ok": True, "score": 100.0, "reasons": ["risk_module_missing"], "metrics": {}}

# ✅ אישורים — ConfirmStore מגיע מ־trade_executor כדי להיות אחיד מול ה-webhook
from utils.trade_executor import ConfirmStore

log = logging.getLogger("algogpt.auto_executor")

# ─────────── Policy & Defaults (ENV) ───────────
ALLOW_MARKET_ENTRY    = os.getenv("ALLOW_MARKET_ENTRY", "1").lower() in ("1","true","yes","on")

# Fallback (סטטי) — יידרס דינמית אם DYNAMIC_POLICY_ENABLE=1
ENTRY_BAND_BPS_FALLBK = float(os.getenv("ENTRY_BAND_BPS", "8.5"))
STOP_BAND_BPS_FALLBK  = float(os.getenv("STOP_BAND_BPS",  "10"))
ESCALATE_AFTER_S_FBK  = float(os.getenv("ESCALATE_AFTER_SEC", "10"))
ESCALATE_SLIP_BPS_FBK = float(os.getenv("ESCALATE_SLIPPAGE_BPS", "15"))
SLIPPAGE_GUARD_BPS_FBK= float(os.getenv("SLIPPAGE_GUARD_BPS", "35"))

# Guards
PERCENT_PRICE_GUARD_BPS = float(os.getenv("PERCENT_PRICE_GUARD_BPS", "45"))
POST_FILL_SANITY_BPS    = float(os.getenv("POST_FILL_SANITY_BPS", "40"))

# Limit offsets (when using LIMIT TP/SL)
SL_LIMIT_OFFSET_BPS   = float(os.getenv("SL_LIMIT_OFFSET_BPS", "8"))
TP_LIMIT_OFFSET_BPS   = float(os.getenv("TP_LIMIT_OFFSET_BPS", "8"))

MIN_QUALITY_SCORE     = float(os.getenv("MIN_QUALITY_SCORE", "4.0"))  # Lower threshold for realistic trading
MAX_ATR_PCT           = float(os.getenv("MAX_ATR_PCT", "2.5"))  # gate לייט
MIN_VOLUME            = float(os.getenv("MIN_VOLUME", "0"))

DEFAULT_QTY_STEP      = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))
DEFAULT_TICK          = float(os.getenv("DEFAULT_PRICE_TICK", "0.01"))
DEFAULT_MIN_NOT       = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

# Ladder config
LADDER_TP_ENABLE      = os.getenv("LADDER_TP_ENABLE", "1") in ("1","true","yes","on")
LADDER_TP_KIND        = os.getenv("LADDER_TP_KIND", "TAKE_PROFIT_MARKET").upper()
LADDER_TP_DEFAULT_PCTS= os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5")
LADDER_TP_DEFAULT_SPLITS=os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25")
LADDER_SL_ENABLE      = os.getenv("LADDER_SL_ENABLE", "0") in ("1","true","yes","on")
LADDER_SL_DEFAULT_PCTS= os.getenv("LADDER_SL_DEFAULT_PCTS", "").strip()
TP_LADDER_COOLDOWN_SEC= int(os.getenv("TP_LADDER_COOLDOWN_SEC", "60"))

# Idempotency
IDEMPOTENCY_TTL_SEC   = int(os.getenv("IDEMPOTENCY_TTL_SEC", "15"))

# Prefix controls for cancels
ORDER_ID_PREFIX                  = os.getenv("ORDER_ID_PREFIX", "").strip()
CANCEL_ONLY_PREFIXED_ORDERS_ENV  = os.getenv("CANCEL_ONLY_PREFIXED_ORDERS", "0").lower() in ("1","true","yes","on")
CANCEL_PREFIX_OVERRIDE           = os.getenv("CANCEL_PREFIX_OVERRIDE", "").strip()

# ✅ תאימות שמות ישנים/חדשים
CANCEL_ONLY_PREFIXED_IN_ONEWAY   = os.getenv("CANCEL_ONLY_PREFIXED_IN_ONEWAY", os.getenv("CANCEL_PREFIX_ONLY_IN_ONEWAY","0")).lower() in ("1","true","yes","on")
CANCEL_ONLY_REDUCE_ONLY          = os.getenv("CANCEL_ONLY_REDUCE_ONLY", os.getenv("CANCEL_ONLY_REDUCEONLY","0")).lower() in ("1","true","yes","on")

# חלון גיל/TTL (סטטי; יידרס דינמית)
CANCEL_MIN_AGE_SEC_FBK           = int(os.getenv("CANCEL_MIN_AGE_SEC", "0"))
CANCEL_MAX_AGE_SEC_FBK           = int(os.getenv("CANCEL_MAX_AGE_SEC", "0"))
CANCEL_TTL_SEC_FBK               = int(os.getenv("CANCEL_TTL_SEC", "0"))
AUTO_CANCEL_TTL_MIN              = int(os.getenv("AUTO_CANCEL_TTL_MIN", "60"))
AUTO_CANCEL_TTL_MAX              = int(os.getenv("AUTO_CANCEL_TTL_MAX", "900"))

# מצב פוזיציה דינמי
POSITION_SIDE_MODE_ENV           = (os.getenv("POSITION_SIDE_MODE", os.getenv("POSITION_MODE_OVERRIDE","auto")) or "auto").strip().lower()
BINANCE_FORCE_HEDGE_MODE         = os.getenv("BINANCE_FORCE_HEDGE_MODE","0").lower() in ("1","true","yes","on")

# Telegram
BOT_TOKEN           = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE            = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
CONFIRM_TTL_SEC     = int(os.getenv("CONFIRM_TTL_SEC", "180"))

# Redis (אופציונלי)
REDIS_URL = os.getenv("REDIS_URL", "").strip()
try:
    import redis  # type: ignore
    _redis_available = bool(REDIS_URL)
except Exception:
    _redis_available = False

# ─────────── Dynamic Policy (ATR-driven) ───────────
DYNAMIC_POLICY_ENABLE   = os.getenv("DYNAMIC_POLICY_ENABLE","1").lower() in ("1","true","yes","on")
DYN_ENTRY_MIN_BPS       = float(os.getenv("DYN_ENTRY_MIN_BPS","5"))
DYN_ENTRY_MAX_BPS       = float(os.getenv("DYN_ENTRY_MAX_BPS","20"))
DYN_STOP_MIN_BPS        = float(os.getenv("DYN_STOP_MIN_BPS","6"))
DYN_STOP_MAX_BPS        = float(os.getenv("DYN_STOP_MAX_BPS","25"))
DYN_ESCALATE_AFTER_MIN  = float(os.getenv("DYN_ESCALATE_AFTER_MIN","5"))
DYN_ESCALATE_AFTER_MAX  = float(os.getenv("DYN_ESCALATE_AFTER_MAX","25"))
DYN_ESCALATE_SLIP_MIN_BPS = float(os.getenv("DYN_ESCALATE_SLIP_MIN_BPS","5"))
DYN_ESCALATE_SLIP_MAX_BPS = float(os.getenv("DYN_ESCALATE_SLIP_MAX_BPS","60"))
DYN_SLIP_GUARD_MIN_BPS  = float(os.getenv("DYN_SLIP_GUARD_MIN_BPS","20"))
DYN_SLIP_GUARD_MAX_BPS  = float(os.getenv("DYN_SLIP_GUARD_MAX_BPS","80"))
DYN_CANCEL_MIN_SEC      = float(os.getenv("DYN_CANCEL_MIN_SEC","5"))
DYN_CANCEL_BASE_SEC     = float(os.getenv("DYN_CANCEL_BASE_SEC","15"))
DYN_CANCEL_MAX_SEC      = float(os.getenv("DYN_CANCEL_MAX_SEC","60"))
DYN_ATR_LOW_PCT         = float(os.getenv("DYN_ATR_LOW_PCT","0.5"))
DYN_ATR_HIGH_PCT        = float(os.getenv("DYN_ATR_HIGH_PCT","3.0"))

# ─────────── Dynamic Leverage (ADX-driven) ───────────
LEVERAGE_DYNAMIC_ENABLE = os.getenv("LEVERAGE_DYNAMIC_ENABLE", "1").lower() in ("1","true","yes","on")
LEV_HARD_CAP            = int(os.getenv("LEV_HARD_CAP", "50"))
LEV_ADX_MAP_JSON        = os.getenv("LEV_ADX_MAP_JSON", '{"30":15,"25":12,"20":9,"0":7}')
LEVERAGE_SYMBOL_CAPS    = os.getenv("LEVERAGE_SYMBOL_CAPS", "")

# ─────────── Dynamic SL (ATR) ───────────
SL_DYNAMIC_ENABLE       = os.getenv("SL_DYNAMIC_ENABLE","1").lower() in ("1","true","yes","on")
SL_ATR_MULT             = float(os.getenv("SL_ATR_MULT","0.6"))
SL_TRAIL_ENABLE         = os.getenv("SL_TRAIL_ENABLE","1").lower() in ("1","true","yes","on")
SL_BREATH_ALLOW         = os.getenv("SL_BREATH_ALLOW","1").lower() in ("1","true","yes","on")

# ─────────── Profit Lock (דינמי) ───────────
PROFIT_LOCK_ENABLE      = os.getenv("PROFIT_LOCK_ENABLE","1").lower() in ("1","true","yes","on")
PROFIT_LOCK_BASE_PCT    = float(os.getenv("PROFIT_LOCK_BASE_PCT","80"))
PROFIT_LOCK_MIN_PCT     = float(os.getenv("PROFIT_LOCK_MIN_PCT","50"))
PROFIT_LOCK_MAX_PCT     = float(os.getenv("PROFIT_LOCK_MAX_PCT","95"))
PROFIT_LOCK_ADX_WEIGHT  = float(os.getenv("PROFIT_LOCK_ADX_WEIGHT","0.50"))
PROFIT_LOCK_ATR_WEIGHT  = float(os.getenv("PROFIT_LOCK_ATR_WEIGHT","0.35"))
PROFIT_LOCK_MOM_WEIGHT  = float(os.getenv("PROFIT_LOCK_MOM_WEIGHT","0.15"))

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def _lerp(a: float, b: float, t: float) -> float:
    t = max(0.0, min(1.0, t))
    return a + (b - a) * t

# ─────────── Database persistence ───────────
def save_trade_to_db(symbol: str, side: str, result: Dict[str, Any], plan: Optional[Dict[str, Any]] = None) -> bool:
    """
    💾 Save trade parameters to PostgreSQL database for retrieval by Fills Watcher and Position Monitor.
    
    This ensures original TP/SL values are accessible after entry, preventing 0.0 calculation issues.
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
        side: Trade direction ("BUY" or "SELL")
        result: Result dict from execute_trade_live containing entry_result and plan data
        plan: Optional plan dict with additional trade parameters
        
    Returns:
        bool: True if saved successfully, False otherwise
    """
    try:
        import psycopg2
        import uuid
        from datetime import datetime
        
        DATABASE_URL = os.getenv("DATABASE_URL")
        if not DATABASE_URL:
            log.warning("[save_trade_to_db] DATABASE_URL not configured - cannot save trade")
            return False
        
        # Extract entry price from result
        entry_result = result.get("entry_result", {})
        entry_price = entry_result.get("price") or result.get("base_price")
        
        if not entry_price:
            log.warning(f"[save_trade_to_db] No entry price found for {symbol}")
            return False
        
        # Extract TP/SL from plan or result
        tp_orders = result.get("tp_orders", [])
        sl_orders = result.get("sl_orders", [])
        
        # Get first TP and SL prices
        tp_price = None
        if tp_orders and len(tp_orders) > 0:
            first_tp = tp_orders[0]
            tp_price = first_tp.get("stopPrice") or first_tp.get("price")
        
        sl_price = None
        if sl_orders and len(sl_orders) > 0:
            first_sl = sl_orders[0]
            sl_price = first_sl.get("stopPrice") or first_sl.get("price")
        
        # Extract other parameters
        qty = result.get("qty") or (plan.get("qty") if plan else None)
        leverage = result.get("leverage") or (plan.get("leverage") if plan else None)
        budget = result.get("budget_used") or (plan.get("budget_usd") if plan else None)
        
        # Generate trade_id (matching Portfolio format)
        trade_id = f"TRD-{uuid.uuid4().hex[:10]}"
        
        # Connect to DB
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Insert trade data
        cursor.execute("""
            INSERT INTO trades_log (
                trade_id, symbol, side, entry, exit, qty, leverage,
                sl, tp, margin, pnl, status, opened_at, closed_at, event, note
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trade_id) DO UPDATE SET
                updated_at = CURRENT_TIMESTAMP
        """, (
            trade_id,
            symbol,
            side,
            float(entry_price),
            None,  # exit - will be updated when trade closes
            float(qty) if qty else None,
            int(leverage) if leverage else None,
            float(sl_price) if sl_price else None,
            float(tp_price) if tp_price else None,
            float(budget) if budget else None,
            None,  # pnl - will be updated when trade closes
            "OPEN",  # status
            datetime.now(),  # opened_at
            None,  # closed_at
            "TRADE_OPENED",  # event
            f"Entry via auto_execute_plan: TP={tp_price}, SL={sl_price}"  # note
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        log.info(f"💾 [save_trade_to_db] Saved {symbol} {side} - Entry: {entry_price}, TP: {tp_price}, SL: {sl_price}")
        return True
        
    except Exception as e:
        log.error(f"[save_trade_to_db] Failed to save trade to PostgreSQL: {e}", exc_info=True)
        return False

# ─────────── Quantize helpers ───────────
def _decimals(step_str: str) -> int:
    if "." not in step_str: return 0
    frac = step_str.split(".")[1].rstrip("0")
    return len(frac)

def _filters(symbol: str) -> Dict[str, Any]:
    return get_symbol_filters(symbol) or {}

def _q_price(symbol: str, price: float) -> Tuple[str, float]:
    f = _filters(symbol); tick = float(f.get("tickSize") or DEFAULT_TICK) or DEFAULT_TICK
    decs = _decimals(str(f.get("tickSize") or DEFAULT_TICK))
    steps = round(price / tick); p = steps * tick
    s = f"{p:.{decs}f}"; return s, float(s)

def _q_qty(symbol: str, qty: float) -> Tuple[str, float]:
    f = _filters(symbol); step = float(f.get("stepSize") or DEFAULT_QTY_STEP) or DEFAULT_QTY_STEP
    decs = _decimals(str(f.get("stepSize") or DEFAULT_QTY_STEP))
    steps = math.floor(qty / step); q = max(step, steps * step)
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

# ─────────── ClientOrderId helper ───────────
def _new_coid(kind: str) -> Optional[str]:
    pref = (ORDER_ID_PREFIX or "").strip()
    if not pref:
        return None
    return f"{pref}_{kind}_{int(time.time()*1000)%10_000_000}"

# ─────────── Klines helpers + EMA/ATR/ADX ───────────
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
    if not trs: return 0.0
    alpha = 1.0/period
    s=None
    for v in trs:
        s = v if s is None else (alpha*v+(1-alpha)*s)
    return float(s or 0.0)

def _adx_from_klines(kl: List[List[float]], period: int = 14) -> float:
    if len(kl) < period + 2:
        return 0.0
    highs = [float(r[2]) for r in kl]
    lows  = [float(r[3]) for r in kl]
    closes= [float(r[4]) for r in kl]
    trs, plusDM, minusDM = [], [], []
    for i in range(1, len(kl)):
        upMove = highs[i] - highs[i-1]
        downMove = lows[i-1] - lows[i]
        trs.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
        plusDM.append(upMove if (upMove > downMove and upMove > 0) else 0.0)
        minusDM.append(downMove if (downMove > upMove and downMove > 0) else 0.0)
    def _wilder_smooth(arr: List[float], p: int) -> List[float]:
        out=[]; s=sum(arr[:p]); out.append(s)
        for i in range(p, len(arr)):
            s = s - (s/p) + arr[i]
            out.append(s)
        return out
    trN    = _wilder_smooth(trs, period)
    plusDMN= _wilder_smooth(plusDM, period)
    minusDMN=_wilder_smooth(minusDM, period)
    di_plus = [ (plusDMN[i] / trN[i]) * 100 if trN[i] > 0 else 0 for i in range(len(trN)) ]
    di_minus= [ (minusDMN[i] / trN[i]) * 100 if trN[i] > 0 else 0 for i in range(len(trN)) ]
    dx = [ (abs(di_plus[i]-di_minus[i]) / max(di_plus[i]+di_minus[i], 1e-12)) * 100 for i in range(len(di_plus)) ]
    adx_vals = _ema(dx, period)
    return float(adx_vals[-1]) if adx_vals else 0.0

def _fetch_klines_raw(symbol: str, interval: str = "1m", limit: int = 60) -> List[List[float]]:
    cli = get_futures_client()
    data = cli.futures_klines(symbol=symbol.upper(), interval=interval, limit=min(1000, max(20, limit)))
    return data or []

# ─────────── Profit-Lock estimator (דינמי) ───────────
def _estimate_profit_lock_pct(adx_now: float, atr_pct: float, mom_pct: float) -> float:
    if not PROFIT_LOCK_ENABLE:
        return 0.0
    adx_t = _clamp(adx_now / 50.0, 0.0, 1.0)
    if DYN_ATR_HIGH_PCT <= DYN_ATR_LOW_PCT:
        atr_t = 0.5
    else:
        atr_t = _clamp((atr_pct - DYN_ATR_LOW_PCT) / (DYN_ATR_HIGH_PCT - DYN_ATR_LOW_PCT), 0.0, 1.0)
    mom_t = _clamp((mom_pct + 0.5) / 1.0, 0.0, 1.0)
    w_adx = PROFIT_LOCK_ADX_WEIGHT
    w_atr = PROFIT_LOCK_ATR_WEIGHT
    w_mom = PROFIT_LOCK_MOM_WEIGHT
    w_sum = max(1e-9, w_adx + w_atr + w_mom)
    mix = (w_adx*adx_t + w_atr*(1.0-atr_t) + w_mom*mom_t) / w_sum
    base = PROFIT_LOCK_BASE_PCT / 100.0
    lo   = PROFIT_LOCK_MIN_PCT  / 100.0
    hi   = PROFIT_LOCK_MAX_PCT  / 100.0
    out  = _clamp(_lerp(base*0.8, base*1.2, mix), lo, hi)
    return round(out * 100.0, 2)

# ─────────── Dynamic policy builder ───────────
def _build_dynamic_policy(symbol: str) -> Dict[str, float]:
    if not DYNAMIC_POLICY_ENABLE:
        return {
            "entry_bps": ENTRY_BAND_BPS_FALLBK,
            "stop_bps": STOP_BAND_BPS_FALLBK,
            "escalate_after_s": ESCALATE_AFTER_S_FBK,
            "escalate_slip_bps": ESCALATE_SLIP_BPS_FBK,
            "slip_guard_bps": SLIPPAGE_GUARD_BPS_FBK,
            "cancel_min_age": float(CANCEL_MIN_AGE_SEC_FBK or 0),
            "cancel_max_age": float(CANCEL_MAX_AGE_SEC_FBK or 0),
            "cancel_ttl": float(CANCEL_TTL_SEC_FBK or 0),
            "atr": None, "atr_pct": None, "last_price": None,
            "adx": None, "mom_pct": None,
        }

    try:
        kl = _fetch_klines_raw(symbol, "1m", 60)
        last = float(kl[-1][4]) if kl else float(get_price(symbol) or futures_mark_price(symbol) or 0)
        atr = _atr_from_klines(kl, 14)
        atr_pct = (atr / last) * 100.0 if last > 0 else DYN_ATR_HIGH_PCT
        closes = [float(r[4]) for r in kl][-5:]
        mom_pct = ((closes[-1] / closes[-4]) - 1.0) * 100.0 if len(closes) >= 4 and closes[-4] > 0 else 0.0
        adx_now = _adx_from_klines(kl, 14)
    except Exception:
        return {
            "entry_bps": ENTRY_BAND_BPS_FALLBK,
            "stop_bps": STOP_BAND_BPS_FALLBK,
            "escalate_after_s": ESCALATE_AFTER_S_FBK,
            "escalate_slip_bps": ESCALATE_SLIP_BPS_FBK,
            "slip_guard_bps": SLIPPAGE_GUARD_BPS_FBK,
            "cancel_min_age": float(CANCEL_MIN_AGE_SEC_FBK or 0),
            "cancel_max_age": float(CANCEL_MAX_AGE_SEC_FBK or 0),
            "cancel_ttl": float(CANCEL_TTL_SEC_FBK or 0),
            "atr": None, "atr_pct": None, "last_price": None,
            "adx": None, "mom_pct": None,
        }

    if DYN_ATR_HIGH_PCT <= DYN_ATR_LOW_PCT:
        t = 0.5
    else:
        t = (atr_pct - DYN_ATR_LOW_PCT) / (DYN_ATR_HIGH_PCT - DYN_ATR_LOW_PCT)
        t = max(0.0, min(1.0, t))

    entry_bps   = _lerp(DYN_ENTRY_MIN_BPS,        DYN_ENTRY_MAX_BPS,        t)
    stop_bps    = _lerp(DYN_STOP_MIN_BPS,         DYN_STOP_MAX_BPS,         t)
    esc_after_s = _lerp(DYN_ESCALATE_AFTER_MIN,   DYN_ESCALATE_AFTER_MAX,   t)
    esc_slip    = _lerp(DYN_ESCALATE_SLIP_MIN_BPS,DYN_ESCALATE_SLIP_MAX_BPS,t)
    slip_guard  = _lerp(DYN_SLIP_GUARD_MIN_BPS,   DYN_SLIP_GUARD_MAX_BPS,   t)

    cmin = _lerp(DYN_CANCEL_MIN_SEC,  DYN_CANCEL_BASE_SEC, t)
    cmax = _lerp(DYN_CANCEL_BASE_SEC, DYN_CANCEL_MAX_SEC,  t)
    cmin = max(0.0, min(cmin, cmax))
    cttl = 0.0

    return {
        "entry_bps": float(entry_bps),
        "stop_bps": float(stop_bps),
        "escalate_after_s": float(esc_after_s),
        "escalate_slip_bps": float(esc_slip),
        "slip_guard_bps": float(slip_guard),
        "cancel_min_age": float(cmin),
        "cancel_max_age": float(cmax),
        "cancel_ttl": float(cttl),
        "atr": float(atr), "atr_pct": float(atr_pct), "last_price": float(last),
        "adx": float(adx_now), "mom_pct": float(mom_pct),
    }

# ─────────── Position mode (auto/hedge/oneway) ───────────
_pos_mode_cache: Optional[str] = None
_pos_mode_cache_ts: float = 0.0

def _detect_position_mode() -> str:
    global _pos_mode_cache, _pos_mode_cache_ts
    now = time.time()
    if _pos_mode_cache and (now - _pos_mode_cache_ts < 10.0):
        return _pos_mode_cache

    if BINANCE_FORCE_HEDGE_MODE:
        _pos_mode_cache, _pos_mode_cache_ts = "HEDGE", now
        return "HEDGE"

    if POSITION_SIDE_MODE_ENV in ("hedge","oneway"):
        mode = "HEDGE" if POSITION_SIDE_MODE_ENV == "hedge" else "ONEWAY"
        _pos_mode_cache, _pos_mode_cache_ts = mode, now
        return mode

    try:
        cli = get_futures_client()
        for m in ("futures_get_position_mode", "futures_position_mode"):
            fn = getattr(cli, m, None)
            if callable(fn):
                r = fn()
                dual = None
                if isinstance(r, dict):
                    dual = r.get("dualSidePosition")
                if isinstance(dual, bool):
                    mode = "HEDGE" if dual else "ONEWAY"
                    _pos_mode_cache, _pos_mode_cache_ts = mode, now
                    return mode
    except Exception as e:
        log.debug("position mode detect failed: %s", e)

    _pos_mode_cache, _pos_mode_cache_ts = "ONEWAY", now
    return "ONEWAY"

def _pos_side_for_open(side: str) -> str:
    """Return positionSide for order placement.
    In ONE-WAY mode (current account setting), always use 'BOTH'.
    In HEDGE mode, would use side (LONG/SHORT)."""
    # Current account is in ONE-WAY MODE → use 'BOTH'
    return "BOTH"

def _pos_side_for_close(entry_side: str) -> str:
    """Return positionSide for closing orders.
    In ONE-WAY mode (current account setting), always use 'BOTH'.
    In HEDGE mode, would use entry_side (LONG/SHORT)."""
    # Current account is in ONE-WAY MODE → use 'BOTH'
    return "BOTH"

# ─────────── Idempotency (Redis/memory) ───────────
class _Idem:
    _mem: Dict[str, float] = {}
    _r = None
    try:
        if _redis_available:
            _r = redis.Redis.from_url(REDIS_URL, decode_responses=True)  # type: ignore
    except Exception as e:
        log.warning("Idempotency redis error: %s", e); _r = None

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

# ─────────── Telegram confirm helpers ───────────
async def send_confirm_request(chat_id: int, title: str, summary_html: str, cid: str) -> Dict[str, Any]:
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN missing"}
    kb = {"inline_keyboard": [[
        {"text": "✅ אישור", "callback_data": f"CONFIRM:APPROVE:{cid}"},
        {"text": "❌ ביטול", "callback_data": f"CONFIRM:REJECT:{cid}"}
    ]]}
    text = f"<b>{title}</b>\n{summary_html}\n\n<b>CID:</b> <code>{cid}</code>"
    async with httpx.AsyncClient(timeout=10.0) as cli:
        r = await cli.post(f"{API_BASE}/sendMessage", data={
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True, "reply_markup": json.dumps(kb)
        })
        try: return r.json()
        except Exception: return {"ok": False, "error": f"http {r.status_code}"}

async def require_approval(chat_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    cid = ConfirmStore.create(chat_id, payload, ttl=CONFIRM_TTL_SEC)
    title = "אישור טרייד"
    summary = (
        f"<b>{payload.get('symbol')}</b> {payload.get('side')}  "
        f"qty={payload.get('qty')} lev={payload.get('leverage')}<br/>"
        f"כניסה: HYBRID (דינמי ATR)"
    )
    await send_confirm_request(chat_id, title, summary, cid)
    t0 = time.time()
    while time.time() - t0 < CONFIRM_TTL_SEC:
        rec = ConfirmStore.get(cid)
        if rec and rec.get("status") in ("approved", "rejected", "expired"):
            return {"cid": cid, "status": rec["status"]}
        await asyncio.sleep(0.5)
    return {"cid": cid, "status": "expired"}

# ─────────── Quality gate לייט ───────────
def _quality_gate(symbol: str, side: str) -> Dict[str, Any]:
    try:
        kl = _fetch_klines_raw(symbol, "1m", 60)
        closes = [float(r[4]) for r in kl]
        vols   = [float(r[5]) for r in kl]
        if len(closes) < 30:
            return {"enter_ok": False, "score": 0.0, "reasons": ["insufficient_data"]}

        ema21 = _ema(closes, 21)[-1]
        ema50 = _ema(closes, 50)[-1]
        last  = closes[-1]
        atr   = _atr_from_klines(kl, 14)
        atr_pct = (atr / last) * 100.0 if last > 0 else 999.0
        mom = (last / closes[-4] - 1.0) * 100.0

        trend_ok = (ema21 > ema50 and last > ema21) if side == "BUY" else (ema21 < ema50 and last < ema21)
        mom_ok   = (mom > 0.05) if side == "BUY" else (mom < -0.05)
        vol_ok   = True if MIN_VOLUME <= 0 else (vols[-1] >= MIN_VOLUME)
        atr_ok   = (atr_pct <= MAX_ATR_PCT) if MAX_ATR_PCT > 0 else True

        score = 0.0
        score += 4.0 if trend_ok else 0.0
        score += 3.0 if mom_ok else 0.0
        score += 2.0 if atr_ok else 0.0
        score += 1.0 if vol_ok else 0.0

        reasons=[]
        if not trend_ok: reasons.append("trend_mismatch")
        if not mom_ok:   reasons.append("weak_momentum")
        if not atr_ok:   reasons.append("atr_too_high")
        if not vol_ok:   reasons.append("low_volume")

        return {"enter_ok": score >= MIN_QUALITY_SCORE, "score": round(score, 2), "reasons": reasons,
                "metrics": {"ema21": ema21, "ema50": ema50, "atr_pct": atr_pct, "mom_pct": mom, "vol1m": vols[-1]}}
    except Exception as e:
        log.warning("quality gate failed: %s", e)
        return {"enter_ok": False, "score": 0.0, "reasons": ["gate_error"]}

# ─────────── Cancel old closing orders ───────────
def _order_age_sec(o: Dict[str, Any]) -> Optional[float]:
    now_ms = int(time.time() * 1000)
    ts_ms = None
    for k in ("time","updateTime","workingTime","createTime"):
        v = o.get(k)
        if isinstance(v, (int, float)) and v > 0:
            ts_ms = max(ts_ms or 0, int(v))
    if ts_ms:
        return max(0.0, (now_ms - ts_ms) / 1000.0)
    return None

def _cancel_old_closing_orders(symbol: str, policy: Optional[Dict[str, float]] = None) -> int:
    try:
        p = policy or {}
        cancel_min = float(p.get("cancel_min_age", 0))
        cancel_max = float(p.get("cancel_max_age", 0))
        ttl = float(p.get("cancel_ttl", 0))
        if ttl <= 0:
            base = (p.get("escalate_after_s") or ESCALATE_AFTER_S_FBK)
            ttl = max(AUTO_CANCEL_TTL_MIN, min(AUTO_CANCEL_TTL_MAX, float(base) * 6.0))

        orders = get_all_orders(symbol, limit=100) or []
        tps = ("TAKE_PROFIT", "TAKE_PROFIT_MARKET")
        sls = ("STOP", "STOP_MARKET")
        pref = (CANCEL_PREFIX_OVERRIDE or ORDER_ID_PREFIX or "").strip()

        pos_mode = _detect_position_mode()
        is_oneway = (pos_mode == "ONEWAY")

        only_pref = False
        if CANCEL_ONLY_PREFIXED_IN_ONEWAY and is_oneway:
            only_pref = True
        elif CANCEL_ONLY_PREFIXED_ORDERS_ENV and pref:
            only_pref = True

        count = 0
        for o in orders:
            st = (o.get("status") or "").upper()
            if st not in ("NEW","PARTIALLY_FILLED"):
                continue
            typ = (o.get("type") or "").upper()
            if typ not in tps + sls:
                continue

            if CANCEL_ONLY_REDUCE_ONLY and not bool(o.get("reduceOnly", False)):
                continue

            age = _order_age_sec(o)
            if age is not None:
                if cancel_min > 0 and age < cancel_min:
                    continue
                if cancel_max > 0 and age > cancel_max:
                    continue

            if only_pref:
                coid = str(o.get("clientOrderId") or o.get("origClientOrderId") or "")
                if not (pref and coid.startswith(pref)):
                    continue

            oid = o.get("orderId")
            if oid is None: continue
            try:
                futures_cancel_order(symbol, oid)
                count += 1
            except Exception as e:
                log.warning("cancel failed %s/%s: %s", symbol, oid, e)
        return count
    except Exception as e:
        log.warning("cancel_old_closing_orders error: %s", e)
        return 0

# ─────────── Ladders build ───────────
def _parse_csv_floats(s: str) -> List[float]:
    out=[]
    for x in (s or "").split(","):
        x=x.strip()
        if not x: continue
        try: out.append(float(x))
        except Exception: continue
    return out

def _build_ladders(sym: str, side: str, qty: float,
                   tp_targets: Optional[List[float]], tp_splits: Optional[List[float]],
                   sl_targets: Optional[List[float]], sl_splits: Optional[List[float]]) -> Dict[str, Any]:
    plan = {"tp_orders": [], "sl_orders": []}
    tp_kind_market = (LADDER_TP_KIND == "TAKE_PROFIT_MARKET")

    def _prep(kind: str, targets, splits, limit_sign):
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
                    plan["tp_orders"].append({
                        "type": "TAKE_PROFIT_MARKET",
                        "stopPrice": stop_p,
                        "qty": qalloc,
                    })
                else:
                    limit_p = _offset_bps(float(t), TP_LIMIT_OFFSET_BPS, limit_sign)
                    _, lim_p = _q_price(sym, limit_p)
                    plan["tp_orders"].append({
                        "type": "TAKE_PROFIT",
                        "stopPrice": stop_p,
                        "price": lim_p,
                        "qty": qalloc,
                    })
            else:  # SL
                limit_p = _offset_bps(float(t), SL_LIMIT_OFFSET_BPS, limit_sign)
                _, lim_p = _q_price(sym, limit_p)
                plan["sl_orders"].append({
                    "type": "STOP",
                    "stopPrice": stop_p,
                    "price": lim_p,
                    "qty": qalloc,
                })

    if tp_targets: _prep("TP", tp_targets, tp_splits, +1 if side=="BUY" else -1)
    if sl_targets: _prep("SL", sl_targets, sl_splits, -1 if side=="BUY" else +1)
    return plan

# ─────────── Hybrid entry + escalation ───────────
async def _place_hybrid_entry(sym: str, side: str, qty: float, base_price: float,
                              ref_entry: Optional[float], is_hedge: bool,
                              pol: Dict[str, float]) -> Dict[str, Any]:
    entry_bps = pol["entry_bps"]; stop_bps = pol["stop_bps"]

    ref = ref_entry if ref_entry is not None else base_price
    if side == "BUY":
        limit_price = _offset_bps(ref, -entry_bps, +1)
        stop_price  = _offset_bps(ref, +stop_bps,  +1)
    else:
        limit_price = _offset_bps(ref, +entry_bps, +1)
        stop_price  = _offset_bps(ref, -stop_bps,  +1)

    cur = get_price(sym) or futures_mark_price(sym) or base_price
    slip_bps_now = abs(cur - ref) / max(ref, 1e-9) * 10000.0
    if slip_bps_now >= pol["slip_guard_bps"]:
        return {"ok": False, "reason": "slippage_guard", "slip_bps": slip_bps_now, "guard_bps": pol["slip_guard_bps"]}

    limit_str, limit_p = _q_price(sym, float(limit_price))
    stop_str , stop_p  = _q_price(sym, float(stop_price))
    qty_str  , _       = _q_qty(sym, qty)

    order_common_open: Dict[str, Any] = {}
    if is_hedge:
        order_common_open["positionSide"] = _pos_side_for_open(side)

    coid_lim = _new_coid("OPEN_LIM") or None
    coid_stp = _new_coid("OPEN_STP") or None

    lim_args = dict(symbol=sym, side=side, type="LIMIT",
                    timeInForce="GTC", price=limit_str, quantity=qty_str, **order_common_open)
    if coid_lim: lim_args["newClientOrderId"] = coid_lim

    stp_args = dict(symbol=sym, side=side, type="STOP",
                    timeInForce="GTC", stopPrice=stop_str, price=stop_str, quantity=qty_str, **order_common_open)
    if coid_stp: stp_args["newClientOrderId"] = coid_stp

    lim = futures_create_order(**lim_args)
    lim_id = str(lim.get("orderId") or "")
    stp = futures_create_order(**stp_args)
    stp_id = str(stp.get("orderId") or "")

    def _is_filled(oid: str) -> Tuple[bool, Optional[float]]:
        try:
            lst = get_all_orders(sym, limit=15) or []
            for o in lst:
                if str(o.get("orderId")) == str(oid):
                    st = (o.get("status") or "").upper()
                    if st in ("FILLED", "PARTIALLY_FILLED"):
                        ap = o.get("avgPrice") or o.get("price")
                        try:
                            return True, float(ap) if ap is not None else None
                        except Exception:
                            return True, None
        except Exception:
            pass
        return False, None

    t0 = time.time()
    while True:
        lim_filled, lim_fill_px = await asyncio.to_thread(_is_filled, lim_id)
        stp_filled, stp_fill_px = await asyncio.to_thread(_is_filled, stp_id)

        if lim_filled and not stp_filled:
            try: futures_cancel_order(sym, stp_id)
            except Exception: pass
            mk = get_price(sym) or futures_mark_price(sym) or lim_fill_px or limit_p
            if mk and lim_fill_px:
                bps = abs(lim_fill_px - mk) / max(mk, 1e-9) * 10000.0
                return {"ok": True, "entry_kind": "LIMIT", "price": lim_fill_px, "sanity_bps": bps, "sanity_ok": bps <= POST_FILL_SANITY_BPS, "order": lim}
            return {"ok": True, "entry_kind": "LIMIT", "price": lim_fill_px or limit_p, "sanity_bps": None, "sanity_ok": True, "order": lim}

        if stp_filled and not lim_filled:
            try: futures_cancel_order(sym, lim_id)
            except Exception: pass
            mk = get_price(sym) or futures_mark_price(sym) or stp_fill_px or stop_p
            if mk and stp_fill_px:
                bps = abs(stp_fill_px - mk) / max(mk, 1e-9) * 10000.0
                return {"ok": True, "entry_kind": "STOP", "price": stp_fill_px, "sanity_bps": bps, "sanity_ok": bps <= POST_FILL_SANITY_BPS, "order": stp}
            return {"ok": True, "entry_kind": "STOP", "price": stp_fill_px or stop_p, "sanity_bps": None, "sanity_ok": True, "order": stp}

        if time.time() - t0 >= float(pol["escalate_after_s"]):
            cur = get_price(sym) or futures_mark_price(sym) or base_price
            slip_bps = abs(cur - limit_p) / max(limit_p, 1e-9) * 10000.0
            gate = _quality_gate(sym, side)
            justified = (gate.get("enter_ok") is True) and (slip_bps >= float(pol["escalate_slip_bps"]))
            if ALLOW_MARKET_ENTRY and justified:
                for oid in (lim_id, stp_id):
                    try:
                        if oid: futures_cancel_order(sym, oid)
                    except Exception: pass
                order_common_mkt: Dict[str, Any] = {}
                if is_hedge:
                    order_common_mkt["positionSide"] = _pos_side_for_open(side)
                mkt_args = dict(symbol=sym, side=side, type="MARKET", quantity=qty_str, **order_common_mkt)
                coid_mkt = _new_coid("OPEN_MKT") or None
                if coid_mkt: mkt_args["newClientOrderId"] = coid_mkt
                mkt = futures_create_order(**mkt_args)
                mk = get_price(sym) or futures_mark_price(sym) or cur
                bps = abs((cur or 0) - (mk or 0)) / max(mk or 1e-9, 1e-9) * 10000.0 if mk and cur else None
                return {"ok": True, "entry_kind": "MARKET_ESCALATE", "price": float(cur), "sanity_bps": bps, "sanity_ok": (bps is None) or (bps <= POST_FILL_SANITY_BPS), "order": mkt}
            t0 = time.time()
        await asyncio.sleep(1.0)

# ─────────── Public API ───────────
async def execute_trade_live(
    symbol: str, side: str, *,
    budget: Optional[float] = None, leverage: int = 0, dry_run: bool = True,
    quantity: Optional[float] = None, entry: Optional[float] = None,
    sl: Optional[float] = None, tp: Optional[float] = None,
    tp_targets: Optional[List[float]] = None, tp_splits: Optional[List[float]] = None,
    sl_targets: Optional[List[float]] = None, sl_splits: Optional[List[float]] = None,
    confirm_first: bool = True, telegram_chat_id: Optional[int] = None,
    position_side: str = "BOTH", reduce_only: bool = False,
) -> Dict[str, Any]:

    side = side.upper().strip()
    if side not in {"BUY","SELL"}:
        raise ValueError("side must be BUY/SELL")
    sym = symbol.upper().strip()

    pos_mode = _detect_position_mode()
    is_hedge = (pos_mode == "HEDGE")

    base_price = get_price(sym) or futures_mark_price(sym)
    if not base_price or base_price <= 0:
        raise RuntimeError(f"Cannot fetch price for {sym}")

    pol = _build_dynamic_policy(sym)

    ref_for_guard = float(entry or base_price)
    mk = float(get_price(sym) or futures_mark_price(sym) or base_price)
    pp_bps = abs(mk - ref_for_guard) / max(ref_for_guard, 1e-9) * 10000.0
    if pp_bps >= PERCENT_PRICE_GUARD_BPS:
        return {"ok": False, "reason": "percent_price_guard", "bps": pp_bps, "mk": mk, "ref": ref_for_guard}

    gate = _quality_gate(sym, side)
    try:
        score_for_budget: Optional[float] = float(gate.get("score")) if gate.get("score") is not None else None
    except Exception:
        score_for_budget = None

    lev_eff = int(leverage or 0)
    try:
        if LEVERAGE_DYNAMIC_ENABLE and lev_eff <= 0:
            adx_now = float(pol.get("adx") or 0.0)
            mapping = json.loads(LEV_ADX_MAP_JSON) if isinstance(LEV_ADX_MAP_JSON, str) else dict(LEV_ADX_MAP_JSON)
            best = 0
            for k, v in mapping.items():
                try:
                    th = float(k); lv = int(v)
                    if adx_now >= th and lv > best:
                        best = lv
                except Exception:
                    continue
            lev_eff = best or 5
        if lev_eff <= 0: lev_eff = 5
        lev_eff = min(lev_eff, LEV_HARD_CAP)
        try:
            caps = json.loads(LEVERAGE_SYMBOL_CAPS) if LEVERAGE_SYMBOL_CAPS else {}
            if sym in caps:
                lev_eff = min(lev_eff, int(caps[sym]))
        except Exception:
            pass
    except Exception as e:
        log.warning("dynamic leverage calc failed: %s", e)
        lev_eff = int(leverage or 5)

    if budget is None or float(budget) <= 0:
        budget = _get_budget(symbol=sym, quality=score_for_budget, atr=pol.get("atr"), price=pol.get("last_price"))

    qty_calc_error = None
    qty: Optional[float] = None
    try:
        qty = _calc_qty(sym, float(base_price), budget, lev_eff, quantity)
    except Exception as e:
        qty_calc_error = str(e)

    risk = pre_trade_risk_check(sym, side, lev_eff, entry)

    idem_payload = {"sym": sym, "side": side, "lev": int(lev_eff),
                    "qty": round(float(qty or 0), 10), "dry": bool(dry_run),
                    "entry_bucket": round(ref_for_guard, 5)}
    if not _Idem.check_and_set(idem_payload, ttl=IDEMPOTENCY_TTL_SEC):
        return {"ok": False, "reason": "idem_conflict", "ttl_sec": IDEMPOTENCY_TTL_SEC}

    if tp is None and not tp_targets and LADDER_TP_ENABLE:
        try:
            tps = [float(x) for x in _parse_csv_floats(LADDER_TP_DEFAULT_PCTS)]
            anchor = float(entry or base_price)
            sign = +1 if side=="BUY" else -1
            tp_targets = [anchor * (1.0 + sign * p/100.0) for p in tps]
            tp_splits = [float(x) for x in _parse_csv_floats(LADDER_TP_DEFAULT_SPLITS)] or None
        except Exception:
            pass

    if sl is None and not sl_targets:
        try:
            anchor = float(entry or base_price)
            if SL_DYNAMIC_ENABLE and pol.get("atr"):
                atr = float(pol["atr"])
                sl_px = (anchor - SL_ATR_MULT*atr) if side == "BUY" else (anchor + SL_ATR_MULT*atr)
                sl_targets = [sl_px]
            elif LADDER_SL_ENABLE and LADDER_SL_DEFAULT_PCTS:
                slps = [float(x) for x in _parse_csv_floats(LADDER_SL_DEFAULT_PCTS)]
                sign = -1 if side=="BUY" else +1
                sl_targets = [anchor * (1.0 + sign * p/100.0) for p in slps]
        except Exception:
            pass

    if dry_run:
        profit_lock_pct = _estimate_profit_lock_pct(
            float(pol.get("adx") or 0.0),
            float(pol.get("atr_pct") or 0.0),
            float(pol.get("mom_pct") or 0.0),
        )
        plan: Dict[str, Any] = {
            "ok": True, "symbol": sym, "side": side, "leverage": lev_eff,
            "base_price": float(base_price), "dry_run": True,
            "entry_policy": f"HYBRID_LIMIT_STOP(dyn {pol['entry_bps']:.2f}/{pol['stop_bps']:.2f}bps)+MARKET_ESCALATE(after~{pol['escalate_after_s']:.0f}s, slip≥{pol['escalate_slip_bps']:.0f}bps)",
            "gate": gate, "risk": risk, "alloc_ok": qty is not None, "alloc_error": qty_calc_error,
            "guards": {"percent_price_bps": pp_bps, "slippage_guard_bps": pol["slip_guard_bps"]},
            "position_mode": pos_mode, "position_side": ("LONG/SHORT" if is_hedge else "BOTH"),
            "reduce_only": reduce_only,
            "cancel_policy": {"min_age": pol["cancel_min_age"], "max_age": pol["cancel_max_age"]},
            "budget_used": float(budget or 0.0),
            "dyn": {"atr_pct": pol.get("atr_pct"), "adx": pol.get("adx"), "mom_pct": pol.get("mom_pct")},
            "profit_lock_policy": {
                "enabled": PROFIT_LOCK_ENABLE,
                "lock_pct": profit_lock_pct,
                "base_pct": PROFIT_LOCK_BASE_PCT,
                "min_pct": PROFIT_LOCK_MIN_PCT,
                "max_pct": PROFIT_LOCK_MAX_PCT,
            }
        }
        if qty is not None:
            ladders = _build_ladders(sym, side, qty,
                                     ([tp] if tp is not None else tp_targets), tp_splits,
                                     ([sl] if sl is not None else sl_targets), sl_splits)
            plan.update({"qty": qty, **ladders})
            plan["entry_simulation"] = {
                "limit_around": _offset_bps(entry or base_price, (-pol["entry_bps"] if side=="BUY" else +pol["entry_bps"]), +1),
                "stop_around":  _offset_bps(entry or base_price, (+pol["stop_bps"]  if side=="BUY" else -pol["stop_bps"]), +1),
                "escalate_after_sec": pol["escalate_after_s"], "escalate_slip_bps": pol["escalate_slip_bps"],
                "allow_market_entry": ALLOW_MARKET_ENTRY,
            }
        return plan

    if qty is None:
        return {"ok": False, "reason": qty_calc_error or "allocation_invalid"}
    if not gate.get("enter_ok"):
        return {"ok": False, "reason": "quality_gate_rejected", "gate": gate}
    if RISK_CHECK_ENABLE and not risk.get("ok", True):
        return {"ok": False, "reason": "risk_check_failed", "risk": risk}

    if confirm_first:
        if not telegram_chat_id:
            return {"ok": False, "reason": "telegram_chat_id_required"}
        approval = await require_approval(telegram_chat_id, {
            "symbol": sym, "side": side, "qty": qty, "leverage": lev_eff
        })
        if approval.get("status") != "approved":
            return {"ok": False, "status": approval.get("status"), "reason": "not_approved"}

    _cancel_old_closing_orders(sym, policy=pol)

    try:
        set_leverage(sym, int(lev_eff))
    except Exception as e:
        log.warning("set_leverage failed: %s", e)

    entry_res = await _place_hybrid_entry(sym, side, qty, float(base_price), entry, is_hedge, pol)
    if not entry_res or (entry_res.get("ok") is False):
        return {"ok": False, "reason": entry_res.get("reason", "entry_failed"), "details": entry_res}

    sanity_ok = bool(entry_res.get("sanity_ok", True))
    sanity_bps = entry_res.get("sanity_bps")

    profit_lock_pct = _estimate_profit_lock_pct(
        float(pol.get("adx") or 0.0),
        float(pol.get("atr_pct") or 0.0),
        float(pol.get("mom_pct") or 0.0),
    )

    plan: Dict[str, Any] = {
        "ok": True, "symbol": sym, "side": side, "qty": qty, "leverage": lev_eff,
        "base_price": float(base_price), "dry_run": False,
        "entry_policy": f"HYBRID_LIMIT_STOP(dyn {pol['entry_bps']:.2f}/{pol['stop_bps']:.2f}bps)+MARKET_ESCALATE(after~{pol['escalate_after_s']:.0f}s, slip≥{pol['escalate_slip_bps']:.0f}bps)",
        "gate": gate, "risk": risk, "entry_result": entry_res,
        "tp_orders": [], "sl_orders": [], "sanity_ok": sanity_ok, "sanity_bps": sanity_bps,
        "position_mode": pos_mode, "cancel_policy": {"min_age": pol["cancel_min_age"], "max_age": pol["cancel_max_age"]},
        "budget_used": float(budget or 0.0),
        "dyn": {"atr_pct": pol.get("atr_pct"), "adx": pol.get("adx"), "mom_pct": pol.get("mom_pct")},
        "profit_lock_policy": {
            "enabled": PROFIT_LOCK_ENABLE,
            "lock_pct": profit_lock_pct,
            "base_pct": PROFIT_LOCK_BASE_PCT,
            "min_pct": PROFIT_LOCK_MIN_PCT,
            "max_pct": PROFIT_LOCK_MAX_PCT,
        }
    }

    close_side = "SELL" if side=="BUY" else "BUY"
    ladders = _build_ladders(sym, side, qty,
                             ([tp] if tp is not None else tp_targets), tp_splits,
                             ([sl] if sl is not None else sl_targets), sl_splits)
    plan["tp_orders"] = ladders["tp_orders"]; plan["sl_orders"] = ladders["sl_orders"]

    for arr in (plan["tp_orders"], plan["sl_orders"]):
        for o in arr:
            typ = str(o.get("type")).upper()
            args: Dict[str, Any] = dict(
                symbol=sym,
                side=close_side,
                type=typ,
                reduceOnly=True,
            )
            if is_hedge:
                args["positionSide"] = _pos_side_for_close(side)

            if "MARKET" not in typ:
                args["timeInForce"] = "GTC"
            # חשוב: תמחור ו־workingType על MARK_PRICE
            if "MARKET" in typ:
                args["stopPrice"] = _q_price(sym, float(o["stopPrice"]))[0]
                args["workingType"] = "MARK_PRICE"
            else:
                args["stopPrice"] = _q_price(sym, float(o["stopPrice"]))[0]
                args["price"]     = _q_price(sym, float(o.get("price", o["stopPrice"])))[0]
                args["workingType"] = "MARK_PRICE"

            args["quantity"] = _q_qty(sym, float(o["qty"]))[0]

            coid_kind = "TP" if "TAKE_PROFIT" in typ else "SL"
            coid = _new_coid(coid_kind) or None
            if coid: args["newClientOrderId"] = coid

            try:
                resp = futures_create_order(**args)
                o["response"] = resp
            except Exception as e:
                o["response"] = {"ok": False, "error": str(e)}

    return plan






















































































































# ─────────── Plan Wrapper (for alerts/ingest auto-execution) ───────────
async def auto_execute_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    🔥 UPGRADED: Routes through ExecutionBot with TradingGatekeeper + SmartOrderRouter + ISOLATED limit!
    
    Wrapper שמקבל plan (מ-/alerts/ingest) ומבצע את הטרייד באמצעות ExecutionBot.
    מחזיר תוצאה עם ok/error + פרטי הביצוע.
    
    🛡️ Protection Layers:
    - TradingGatekeeper (symbol filters, quality, dynamic leverage)
    - SmartOrderRouter (LIMIT/MARKET decision)
    - ISOLATED positions counter (4 max)
    - Post-Entry Verification (SL+TP enforcement)
    """
    print(f"🔧 [auto_execute_plan] ENTERED function (ExecutionBot mode)")
    try:
        from utils.execution_bot import ExecutionBot
        
        symbol = str(plan.get("symbol", "")).upper()
        side = str(plan.get("side", "")).upper()
        print(f"🔧 [auto_execute_plan] Processing {symbol} {side}")
        
        # המר LONG/SHORT ל-BUY/SELL
        if side == "LONG":
            side = "BUY"
        elif side == "SHORT":
            side = "SELL"
        
        if not symbol or side not in ("BUY", "SELL"):
            return {"ok": False, "error": "invalid_symbol_or_side"}
        
        # חלץ פרמטרים
        leverage = int(plan.get("leverage", 5))
        budget = float(plan.get("budget_usd") or 0) or None
        qty = float(plan.get("qty") or 0) or None
        entry = float(plan.get("entry") or 0) or None
        
        # חלץ TP/SL
        tp_list = plan.get("tp", [])
        sl_dict = plan.get("sl", {})
        
        # TP ראשון
        tp1 = None
        if tp_list and len(tp_list) > 0:
            if isinstance(tp_list[0], dict):
                tp1 = float(tp_list[0].get("price", 0)) or None
            elif isinstance(tp_list[0], (int, float)):
                tp1 = float(tp_list[0]) or None
        
        # SL
        sl = None
        if isinstance(sl_dict, dict):
            sl = float(sl_dict.get("stopPrice", 0)) or None
        elif isinstance(sl_dict, (int, float)):
            sl = float(sl_dict) or None
        
        # 🚀 CRITICAL FIX: Route through ExecutionBot with all protections!
        dry_run = os.getenv("DRY_RUN", "0").lower() in ("1", "true", "yes", "on")
        
        # 🛡️ CRITICAL: Normalize atr_pct - .get() returns None if key exists but value is None!
        atr_pct = plan.get("atr_pct")
        if atr_pct is None:
            atr_pct = 0.02  # Default 2% volatility
        
        # Build ticket for ExecutionBot (matches open_position signature)
        ticket_exec = {
            "symbol": symbol,
            "side": side,
            "leverage": leverage,
            "budget_usd": budget,
            "budget": budget,
            "quantity": qty,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "dry_run": dry_run,
            "confirm_first": False,  # Already in FULL AUTO mode
            "reduce_only": False,
            # Metadata for SmartRouter and Gatekeeper
            "quality_score": plan.get("quality") or plan.get("score") or plan.get("success_pct", 0) / 10,
            "atr_pct": atr_pct,
            "spread_pct": plan.get("spread_pct"),
            "signal_age": plan.get("signal_age"),
            "urgency": "normal",
        }
        
        # Instantiate ExecutionBot and execute with ALL protections
        bot = ExecutionBot()
        result = await bot.open_position(ticket_exec, source="auto")
        
        # 💾 CRITICAL: Save trade parameters to database IMMEDIATELY after entry
        if result.get("ok") and not dry_run:
            try:
                saved = save_trade_to_db(symbol, side, result, plan)
                if saved:
                    log.info(f"💾 Trade parameters saved to DB for {symbol}")
                else:
                    log.warning(f"⚠️ Failed to save trade parameters to DB for {symbol}")
            except Exception as e:
                log.error(f"Error saving trade to DB: {e}", exc_info=True)
        
        # 🛡️ LAYER 2: Post-Entry Verification - Ensure SL+TP exist!
        if result.get("ok") and not dry_run:
            try:
                from utils.emergency_protection import get_emergency_protection
                emergency = get_emergency_protection()
                
                entry_qty = result.get("entry_result", {}).get("qty") or result.get("qty") or qty
                
                # 🛡️ CRITICAL FIX: Use Binance's positionSide AS-IS!
                # One-Way Mode: positionSide = 'BOTH'
                # Hedge Mode: positionSide = 'LONG' or 'SHORT'
                entry_result = result.get("entry_result", {})
                position_side = entry_result.get("positionSide") or result.get("position_side") or "BOTH"
                
                log.info(f"🔍 positionSide from Binance: {position_side}")
                
                if entry_qty:
                    log.info(f"🔍 Running post-entry verification for {symbol} {side} positionSide={position_side} qty={entry_qty}")
                    
                    # 🛡️ CRITICAL FIX: Pass positionSide for Hedge Mode
                    is_protected = emergency.post_entry_verification(
                        symbol=symbol,
                        side=side,
                        qty=abs(float(entry_qty)),
                        position_side=position_side
                    )
                    
                    if not is_protected:
                        log.critical(f"🚨 {symbol} {position_side} FAILED post-entry verification - position was emergency closed")
                        result["post_entry_verification"] = "FAILED"
                        result["emergency_closed"] = True
                    else:
                        log.info(f"✅ {symbol} {position_side} PASSED post-entry verification")
                        result["post_entry_verification"] = "PASSED"
            
            except RuntimeError as e:
                # 🔴 CRITICAL: Emergency close FAILED - position remains unprotected!
                log.critical(f"🔴🔴🔴 FATAL: Emergency close FAILED for {symbol} {position_side}: {e}")
                result["ok"] = False  # 🔴 CRITICAL FIX: Mark trade as FAILED!
                result["post_entry_verification"] = "FAILED"
                result["emergency_close_failed"] = True
                result["error"] = str(e)
                # Circuit breaker already triggered - trading will halt by emergency_protection
                
            except Exception as e:
                log.error(f"Post-entry verification error for {symbol}: {e}", exc_info=True)
                result["post_entry_verification_error"] = str(e)
        
        # 📱 Send Telegram notification for successful trade entry
        if result.get("ok") and not dry_run:
            try:
                from utils.telegram_notifier import send_trade_opened
                
                # Build notification data
                entry_price = result.get("entry_result", {}).get("price") or plan.get("entry") or plan.get("base_price")
                
                notify_data = {
                    "plan": {
                        "symbol": symbol,
                        "side": side,
                        "qty": qty,
                        "entry_price": entry_price,
                        "order_type": plan.get("order_type", "MARKET"),
                        "leverage": leverage,
                        "trade_kind": "Futures",
                        "tp": tp_list,
                        "sl": sl_dict,
                    }
                }
                
                await send_trade_opened(notify_data)
                log.info(f"📱 Trade opened notification sent for {symbol}")
            except Exception as e:
                log.error(f"Failed to send trade opened notification: {e}", exc_info=True)
        
        return result
        
    except Exception as e:
        log.error(f"auto_execute_plan failed: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}

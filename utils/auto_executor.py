# utils/trade_executor.py
from __future__ import annotations
import os, math, time, logging, asyncio, json, hashlib
from typing import Optional, Dict, Any, List, Tuple

import httpx

from utils.binance_client import (
    get_price, futures_mark_price, set_leverage, futures_create_order,
    get_symbol_filters, get_all_orders, futures_cancel_order, get_futures_client
)

# ✅ Risk (אופציונלי)
try:
    from utils.risk_checker import pre_trade_risk_check, RISK_CHECK_ENABLE
except Exception:
    RISK_CHECK_ENABLE = False
    def pre_trade_risk_check(*args, **kwargs):  # type: ignore
        return {"ok": True, "score": 100.0, "reasons": ["risk_module_missing"], "metrics": {}}

log = logging.getLogger("algogpt.trade_executor")

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

# Limit offsets (when using LIMIT TP/SL)
SL_LIMIT_OFFSET_BPS   = float(os.getenv("SL_LIMIT_OFFSET_BPS", "8"))
TP_LIMIT_OFFSET_BPS   = float(os.getenv("TP_LIMIT_OFFSET_BPS", "8"))

MIN_QUALITY_SCORE     = float(os.getenv("MIN_QUALITY_SCORE", "8.5"))
MAX_ATR_PCT           = float(os.getenv("MAX_ATR_PCT", "2.5"))
MIN_VOLUME            = float(os.getenv("MIN_VOLUME", "0"))

DEFAULT_QTY_STEP      = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))
DEFAULT_TICK          = float(os.getenv("DEFAULT_PRICE_TICK", "0.01"))
DEFAULT_MIN_NOT       = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

# Ladder config
LADDER_TP_ENABLE      = os.getenv("LADDER_TP_ENABLE", "1") in ("1","true","yes","on")
LADDER_TP_KIND        = os.getenv("LADDER_TP_KIND", "TAKE_PROFIT_MARKET").upper()  # TAKE_PROFIT or TAKE_PROFIT_MARKET
LADDER_TP_DEFAULT_PCTS= os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5")
LADDER_TP_DEFAULT_SPLITS=os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25")
LADDER_SL_ENABLE      = os.getenv("LADDER_SL_ENABLE", "0") in ("1","true","yes","on")
LADDER_SL_DEFAULT_PCTS= os.getenv("LADDER_SL_DEFAULT_PCTS", "").strip()
TP_LADDER_COOLDOWN_SEC= int(os.getenv("TP_LADDER_COOLDOWN_SEC", "60"))

# Idempotency
IDEMPOTENCY_TTL_SEC   = int(os.getenv("IDEMPOTENCY_TTL_SEC", "15"))

# Prefix controls for cancels
ORDER_ID_PREFIX                  = os.getenv("ORDER_ID_PREFIX", "").strip()
CANCEL_ONLY_PREFIXED_ORDERS      = os.getenv("CANCEL_ONLY_PREFIXED_ORDERS", "0") in ("1","true","yes","on")
CANCEL_PREFIX_OVERRIDE           = os.getenv("CANCEL_PREFIX_OVERRIDE", "").strip()

# ✅ ביטול חכם (ENV חדשים/נתמכים)
CANCEL_ONLY_PREFIXED_IN_ONEWAY   = os.getenv("CANCEL_ONLY_PREFIXED_IN_ONEWAY", os.getenv("CANCEL_PREFIX_ONLY_IN_ONEWAY","0")).lower() in ("1","true","yes","on")
# תמיכה גם בגרסאות שם שונות:
CANCEL_ONLY_REDUCE_ONLY          = (os.getenv("CANCEL_ONLY_REDUCE_ONLY", os.getenv("CANCEL_ONLY_REDUCEONLY","0")).lower() in ("1","true","yes","on"))
CANCEL_MIN_AGE_SEC               = int(os.getenv("CANCEL_MIN_AGE_SEC", "0"))
CANCEL_MAX_AGE_SEC               = int(os.getenv("CANCEL_MAX_AGE_SEC", "0"))

# מצב פוזיציה דינמי
POSITION_SIDE_MODE_ENV           = (os.getenv("POSITION_SIDE_MODE", os.getenv("POSITION_MODE_OVERRIDE","auto")) or "auto").strip().lower()
BINANCE_FORCE_HEDGE_MODE         = os.getenv("BINANCE_FORCE_HEDGE_MODE","0").lower() in ("1","true","yes","on")

# Telegram
BOT_TOKEN           = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE            = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
CONFIRM_TTL_SEC     = int(os.getenv("CONFIRM_TTL_SEC", "180"))

# Redis (אופציונלי) — לאידמפוטנציה ועוד
REDIS_URL = os.getenv("REDIS_URL", "").strip()
try:
    import redis  # type: ignore
    _redis_available = bool(REDIS_URL)
except Exception:
    _redis_available = False

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

# ─────────── Position mode (auto/hedge/oneway) ───────────
_pos_mode_cache: Optional[str] = None
_pos_mode_cache_ts: float = 0.0

def _detect_position_mode() -> str:
    """מחזיר 'HEDGE' או 'ONEWAY'."""
    global _pos_mode_cache, _pos_mode_cache_ts
    now = time.time()
    if _pos_mode_cache and (now - _pos_mode_cache_ts < 10.0):
        return _pos_mode_cache

    # 1) force hedge via ENV
    if BINANCE_FORCE_HEDGE_MODE:
        _pos_mode_cache, _pos_mode_cache_ts = "HEDGE", now
        return "HEDGE"

    # 2) explicit env
    if POSITION_SIDE_MODE_ENV in ("hedge","oneway"):
        mode = "HEDGE" if POSITION_SIDE_MODE_ENV == "hedge" else "ONEWAY"
        _pos_mode_cache, _pos_mode_cache_ts = mode, now
        return mode

    # 3) auto-detect via API (best-effort)
    try:
        cli = get_futures_client()
        # most python-binance versions: futures_get_position_mode -> {'dualSidePosition': True/False}
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

    # fallback default
    _pos_mode_cache, _pos_mode_cache_ts = "ONEWAY", now
    return "ONEWAY"

def _pos_side_for_open(side: str) -> str:
    return "LONG" if side == "BUY" else "SHORT"

def _pos_side_for_close(entry_side: str) -> str:
    # סגירת לונג = LONG, סגירת שורט = SHORT
    return "LONG" if entry_side == "BUY" else "SHORT"

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
        # memory fallback
        ts = cls._mem.get(k, 0.0)
        if now - ts < ttl:
            return False
        cls._mem[k] = now
        # cleanup (best-effort)
        for kk, vv in list(cls._mem.items()):
            if now - vv > ttl * 2:
                cls._mem.pop(kk, None)
        return True

# ─────────── Telegram Confirm Store (memory/redis) ───────────
class ConfirmStore:
    _mem: Dict[str, Dict[str, Any]] = {}
    _r = None
    try:
        if _redis_available:
            _r = redis.Redis.from_url(REDIS_URL, decode_responses=True)  # type: ignore
    except Exception as e:
        log.warning("Redis unavailable: %s", e); _r = None

    @classmethod
    def create(cls, chat_id: int, payload: Dict[str, Any], ttl: int = CONFIRM_TTL_SEC) -> str:
        cid = f"cid_{int(time.time()*1000)}_{os.getpid()}_{abs(hash(os.urandom(8)))}"
        rec = {"status": "pending", "payload": payload, "chat_id": chat_id, "created_at": time.time()}
        if cls._r: cls._r.setex(f"confirm:{cid}", ttl, json.dumps(rec))
        else: cls._mem[cid] = rec
        return cid

    @classmethod
    def _load(cls, cid: str) -> Optional[Dict[str, Any]]:
        if cls._r:
            v = cls._r.get(f"confirm:{cid}")
            return json.loads(v) if v else None
        return cls._mem.get(cid)

    @classmethod
    def get(cls, cid: str) -> Optional[Dict[str, Any]]:
        rec = cls._load(cid)
        if not rec: return None
        if rec.get("status") == "pending" and time.time() - rec["created_at"] > CONFIRM_TTL_SEC:
            rec["status"] = "expired"
            if cls._r: cls._r.setex(f"confirm:{cid}", 60, json.dumps(rec))
            else: cls._mem[cid] = rec
        return rec

    @classmethod
    def _save(cls, cid: str, rec: Dict[str, Any]) -> None:
        if cls._r: cls._r.setex(f"confirm:{cid}", 60, json.dumps(rec))
        else: cls._mem[cid] = rec

    @classmethod
    def approve(cls, cid: str, approver: str = "") -> None:
        rec = cls.get(cid); 
        if not rec: return
        rec["status"] = "approved"; rec["approver"] = approver; cls._save(cid, rec)

    @classmethod
    def reject(cls, cid: str, approver: str = "") -> None:
        rec = cls.get(cid)
        if not rec: return
        rec["status"] = "rejected"; rec["approver"] = approver; cls._save(cid, rec)

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
        f"כניסה: HYBRID (Limit±{ENTRY_BAND_BPS}bps / Stop±{STOP_BAND_BPS}bps)"
    )
    await send_confirm_request(chat_id, title, summary, cid)
    t0 = time.time()
    while time.time() - t0 < CONFIRM_TTL_SEC:
        rec = ConfirmStore.get(cid)
        if rec and rec.get("status") in ("approved", "rejected", "expired"):
            return {"cid": cid, "status": rec["status"]}
        await asyncio.sleep(0.5)
    return {"cid": cid, "status": "expired"}

# ─────────── Light indicators (no pandas) ───────────
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
    # Wilder RMA via EMA(alpha=1/period)
    alpha = 1.0/period
    s=None
    for v in trs:
        s = v if s is None else (alpha*v+(1-alpha)*s)
    return float(s or 0.0)

def _fetch_klines_raw(symbol: str, interval: str = "1m", limit: int = 60) -> List[List[float]]:
    cli = get_futures_client()
    data = cli.futures_klines(symbol=symbol.upper(), interval=interval, limit=min(1000, max(10, limit)))
    return data or []

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
        atr_ok   = (atr_pct <= MAX_ATR_PCT)

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

# ─────────── Cancel old closing orders (TP/SL) — חכם ───────────
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

def _cancel_old_closing_orders(symbol: str) -> int:
    """
    מכניס לוגיקה:
      • אם CANCEL_ONLY_PREFIXED_IN_ONEWAY=1 ובפועל המצב ONEWAY → נבטל רק עם prefix.
      • אחרת אם CANCEL_ONLY_PREFIXED_ORDERS=1 → תמיד נבטל רק עם prefix.
      • אם CANCEL_ONLY_REDUCE_ONLY=1 → נבטל רק הזמנות עם reduceOnly=true.
      • סף גיל: CANCEL_MIN_AGE_SEC / CANCEL_MAX_AGE_SEC (אם >0, חייב לעמוד בסף).
    """
    try:
        orders = get_all_orders(symbol, limit=100) or []
        tps = ("TAKE_PROFIT", "TAKE_PROFIT_MARKET")
        sls = ("STOP", "STOP_MARKET")
        pref = (CANCEL_PREFIX_OVERRIDE or ORDER_ID_PREFIX or "").strip()
        pos_mode = _detect_position_mode()   # 'HEDGE' / 'ONEWAY'
        is_oneway = (pos_mode == "ONEWAY")
        only_pref = False
        if CANCEL_ONLY_PREFIXED_IN_ONEWAY and is_oneway:
            only_pref = True
        elif CANCEL_ONLY_PREFIXED_ORDERS and pref:
            only_pref = True

        count = 0
        for o in orders:
            st = (o.get("status") or "").upper()
            if st not in ("NEW","PARTIALLY_FILLED"):  # cancel only active
                continue
            typ = (o.get("type") or "").upper()
            if typ not in tps + sls:
                continue

            # ReduceOnly filter
            if CANCEL_ONLY_REDUCE_ONLY:
                ro = bool(o.get("reduceOnly", False))
                if not ro:
                    continue

            # Age window filter
            age = _order_age_sec(o)
            if age is not None:
                if CANCEL_MIN_AGE_SEC > 0 and age < CANCEL_MIN_AGE_SEC:
                    continue
                if CANCEL_MAX_AGE_SEC > 0 and age > CANCEL_MAX_AGE_SEC:
                    continue

            # Prefix filter
            if only_pref:
                coid = str(o.get("clientOrderId") or o.get("origClientOrderId") or "")
                if not (pref and coid.startswith(pref)):
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
            stop_str, stop_p = _q_price(sym, float(t))

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

# ─────────── Hybrid entry + escalation (עם positionSide ב-HEDGE) ───────────
async def _place_hybrid_entry(sym: str, side: str, qty: float, base_price: float,
                              ref_entry: Optional[float], is_hedge: bool) -> Dict[str, Any]:
    ref = ref_entry if ref_entry is not None else base_price
    if side == "BUY":
        limit_price = _offset_bps(ref, -ENTRY_BAND_BPS, +1)
        stop_price  = _offset_bps(ref, +STOP_BAND_BPS,  +1)
    else:
        limit_price = _offset_bps(ref, +ENTRY_BAND_BPS, +1)
        stop_price  = _offset_bps(ref, -STOP_BAND_BPS,  +1)

    # Slippage guard מול המחיר העדכני לפני פתיחת הזמנות
    cur = get_price(sym) or futures_mark_price(sym) or base_price
    slip_bps_now = abs(cur - ref) / max(ref, 1e-9) * 10000.0
    if slip_bps_now >= SLIPPAGE_GUARD_BPS:
        return {"ok": False, "reason": "slippage_guard", "slip_bps": slip_bps_now}

    limit_str, limit_p = _q_price(sym, limit_price)
    stop_str , stop_p  = _q_price(sym, stop_price)
    qty_str  , _       = _q_qty(sym, qty)

    order_common_open = {}
    if is_hedge:
        order_common_open["positionSide"] = _pos_side_for_open(side)

    lim = futures_create_order(symbol=sym, side=side, type="LIMIT",
                               timeInForce="GTC", price=limit_str, quantity=qty_str,
                               **order_common_open)
    lim_id = str(lim.get("orderId") or "")
    stp = futures_create_order(symbol=sym, side=side, type="STOP",
                               timeInForce="GTC", stopPrice=stop_str, price=stop_str, quantity=qty_str,
                               **order_common_open)
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

        if time.time() - t0 >= ESCALATE_AFTER_S:
            cur = get_price(sym) or futures_mark_price(sym) or base_price
            slip_bps = abs(cur - limit_p) / max(limit_p, 1e-9) * 10000.0
            gate = _quality_gate(sym, side)
            justified = (gate.get("enter_ok") is True) and (slip_bps >= ESCALATE_SLIP_BPS)
            if ALLOW_MARKET_ENTRY and justified:
                try:
                    if lim_id: futures_cancel_order(sym, lim_id)
                except Exception: pass
                try:
                    if stp_id: futures_cancel_order(sym, stp_id)
                except Exception: pass
                order_common_mkt = {}
                if is_hedge:
                    order_common_mkt["positionSide"] = _pos_side_for_open(side)
                mkt = futures_create_order(symbol=sym, side=side, type="MARKET", quantity=qty_str, **order_common_mkt)
                mk = get_price(sym) or futures_mark_price(sym) or cur
                bps = abs((cur or 0) - (mk or 0)) / max(mk or 1e-9, 1e-9) * 10000.0 if mk and cur else None
                return {"ok": True, "entry_kind": "MARKET_ESCALATE", "price": float(cur), "sanity_bps": bps, "sanity_ok": (bps is None) or (bps <= POST_FILL_SANITY_BPS), "order": mkt}
            t0 = time.time()
        await asyncio.sleep(1.0)

# ─────────── Public API ───────────
async def execute_trade_live(
    symbol: str, side: str, *,
    budget: Optional[float] = None, leverage: int = 5, dry_run: bool = True,
    quantity: Optional[float] = None, entry: Optional[float] = None,
    sl: Optional[float] = None, tp: Optional[float] = None,
    tp_targets: Optional[List[float]] = None, tp_splits: Optional[List[float]] = None,
    sl_targets: Optional[List[float]] = None, sl_splits: Optional[List[float]] = None,
    confirm_first: bool = True, telegram_chat_id: Optional[int] = None,
    # תאימות לאחור:
    position_side: str = "BOTH", reduce_only: bool = False,
) -> Dict[str, Any]:

    side = side.upper().strip()
    if side not in {"BUY","SELL"}:
        raise ValueError("side must be BUY/SELL")
    sym = symbol.upper().strip()

    # מצב פוזיציה בפועל (דינמי)
    pos_mode = _detect_position_mode()     # 'HEDGE' / 'ONEWAY'
    is_hedge = (pos_mode == "HEDGE")

    base_price = get_price(sym) or futures_mark_price(sym)
    if not base_price or base_price <= 0:
        raise RuntimeError(f"Cannot fetch price for {sym}")

    # Percent-Price Guard
    ref_for_guard = float(entry or base_price)
    mk = float(get_price(sym) or futures_mark_price(sym) or base_price)
    pp_bps = abs(mk - ref_for_guard) / max(ref_for_guard, 1e-9) * 10000.0
    if pp_bps >= PERCENT_PRICE_GUARD_BPS:
        return {"ok": False, "reason": "percent_price_guard", "bps": pp_bps, "mk": mk, "ref": ref_for_guard}

    qty_calc_error = None
    qty: Optional[float] = None
    try:
        qty = _calc_qty(sym, base_price, budget, leverage, quantity)
    except Exception as e:
        qty_calc_error = str(e)

    gate = _quality_gate(sym, side)

    # ✅ Risk preview
    risk = pre_trade_risk_check(sym, side, leverage, entry)

    # Idempotency Shield
    idem_payload = {"sym": sym, "side": side, "lev": int(leverage),
                    "qty": round(float(qty or 0), 10), "dry": bool(dry_run),
                    "entry_bucket": round(ref_for_guard, 5)}
    if not _Idem.check_and_set(idem_payload, ttl=IDEMPOTENCY_TTL_SEC):
        return {"ok": False, "reason": "idem_conflict", "ttl_sec": IDEMPOTENCY_TTL_SEC}

    # הרחבת TP/SL מסטרינגים ב-ENV אם לא הגיעו מבחוץ
    if tp is None and not tp_targets and LADDER_TP_ENABLE:
        try:
            tps = [float(x) for x in _parse_csv_floats(LADDER_TP_DEFAULT_PCTS)]
            anchor = float(entry or base_price)
            sign = +1 if side=="BUY" else -1
            tp_targets = [anchor * (1.0 + sign * p/100.0) for p in tps]
            tp_splits = [float(x) for x in _parse_csv_floats(LADDER_TP_DEFAULT_SPLITS)] or None
        except Exception:
            pass
    if sl is None and not sl_targets and LADDER_SL_ENABLE and LADDER_SL_DEFAULT_PCTS:
        try:
            slps = [float(x) for x in _parse_csv_floats(LADDER_SL_DEFAULT_PCTS)]
            anchor = float(entry or base_price)
            sign = -1 if side=="BUY" else +1
            sl_targets = [anchor * (1.0 + sign * p/100.0) for p in slps]
        except Exception:
            pass

    if dry_run:
        plan: Dict[str, Any] = {
            "ok": True, "symbol": sym, "side": side, "leverage": leverage,
            "base_price": base_price, "dry_run": True,
            "entry_policy": f"HYBRID_LIMIT_STOP({ENTRY_BAND_BPS}/{STOP_BAND_BPS}bps)+MARKET_ESCALATION",
            "gate": gate, "risk": risk, "alloc_ok": qty is not None, "alloc_error": qty_calc_error,
            "guards": {"percent_price_bps": pp_bps, "slippage_guard_bps": SLIPPAGE_GUARD_BPS},
            "position_mode": pos_mode, "position_side": ("LONG/SHORT" if is_hedge else "BOTH"),
            "reduce_only": reduce_only,
        }
        if qty is not None:
            ladders = _build_ladders(sym, side, qty,
                                     ([tp] if tp is not None else tp_targets), tp_splits,
                                     ([sl] if sl is not None else sl_targets), sl_splits)
            plan.update({"qty": qty, **ladders})
            plan["entry_simulation"] = {
                "limit_around": _offset_bps(entry or base_price, (-ENTRY_BAND_BPS if side=="BUY" else +ENTRY_BAND_BPS), +1),
                "stop_around":  _offset_bps(entry or base_price, (+STOP_BAND_BPS  if side=="BUY" else -STOP_BAND_BPS ), +1),
                "escalate_after_sec": ESCALATE_AFTER_S, "escalate_slip_bps": ESCALATE_SLIP_BPS,
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
            "symbol": sym, "side": side, "qty": qty, "leverage": leverage
        })
        if approval.get("status") != "approved":
            return {"ok": False, "status": approval.get("status"), "reason": "not_approved"}

    # Hygiene: בטל TP/SL קודמים לפי המדיניות החכמה
    _cancel_old_closing_orders(sym)

    try:
        set_leverage(sym, int(leverage))
    except Exception as e:
        log.warning("set_leverage failed: %s", e)

    entry_res = await _place_hybrid_entry(sym, side, qty, base_price, entry, is_hedge)
    if not entry_res or (entry_res.get("ok") is False):
        return {"ok": False, "reason": entry_res.get("reason", "entry_failed"), "details": entry_res}

    sanity_ok = bool(entry_res.get("sanity_ok", True))
    sanity_bps = entry_res.get("sanity_bps")

    plan: Dict[str, Any] = {
        "ok": True, "symbol": sym, "side": side, "qty": qty, "leverage": leverage,
        "base_price": base_price, "dry_run": False,
        "entry_policy": f"HYBRID_LIMIT_STOP({ENTRY_BAND_BPS}/{STOP_BAND_BPS}bps)+MARKET_ESCALATION",
        "gate": gate, "risk": risk, "entry_result": entry_res,
        "tp_orders": [], "sl_orders": [],
        "sanity_ok": sanity_ok, "sanity_bps": sanity_bps,
        "position_mode": pos_mode,
    }

    close_side = "SELL" if side=="BUY" else "BUY"
    ladders = _build_ladders(sym, side, qty,
                             ([tp] if tp is not None else tp_targets), tp_splits,
                             ([sl] if sl is not None else sl_targets), sl_splits)
    plan["tp_orders"] = ladders["tp_orders"]; plan["sl_orders"] = ladders["sl_orders"]

    # שליחת TP/SL עם ReduceOnly + positionSide במצב HEDGE
    for arr in (plan["tp_orders"], plan["sl_orders"]):
        for o in arr:
            typ = str(o.get("type")).upper()
            args: Dict[str, Any] = dict(
                symbol=sym, side=close_side, type=typ,
                reduceOnly=True, timeInForce="GTC",
            )
            if is_hedge:
                args["positionSide"] = _pos_side_for_close(side)

            if "MARKET" in typ:
                args["stopPrice"] = _q_price(sym, float(o["stopPrice"]))[0]
            else:
                args["stopPrice"] = _q_price(sym, float(o["stopPrice"]))[0]
                args["price"]     = _q_price(sym, float(o.get("price", o["stopPrice"])))[0]

            args["quantity"] = _q_qty(sym, float(o["qty"]))[0]
            try:
                resp = futures_create_order(**args)
                o["response"] = resp
            except Exception as e:
                o["response"] = {"ok": False, "error": str(e)}

    return plan












































































































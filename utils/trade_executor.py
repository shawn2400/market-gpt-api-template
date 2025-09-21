# utils/trade_executor.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, math, time, logging, asyncio, json, hashlib
from typing import Optional, Dict, Any, List, Tuple

import httpx

from utils.binance_client import (
    get_price, futures_mark_price, set_leverage, futures_create_order,
    get_symbol_filters, get_all_orders, futures_cancel_order, get_futures_client,
    futures_balance,
)

# ====== Optional dynamic budget hook ======
try:
    from utils.budget import get_budget_usdt
except Exception:
    def get_budget_usdt(symbol: Optional[str] = None, *, quality: Optional[float] = None,
                        atr: Optional[float] = None, price: Optional[float] = None) -> float:  # type: ignore
        try:
            return float(os.getenv("MAX_TRADE_BUDGET", "100"))
        except Exception:
            return 100.0

# ====== Optional risk hook ======
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
LADDER_TP_ENABLE          = os.getenv("LADDER_TP_ENABLE", "1") in ("1","true","yes","on")
LADDER_TP_KIND            = os.getenv("LADDER_TP_KIND", "TAKE_PROFIT_MARKET").upper()
LADDER_TP_DEFAULT_PCTS    = os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5")
LADDER_TP_DEFAULT_SPLITS  = os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25")
LADDER_SL_ENABLE          = os.getenv("LADDER_SL_ENABLE", "1") in ("1","true","yes","on")
LADDER_SL_DEFAULT_PCTS    = os.getenv("LADDER_SL_DEFAULT_PCTS", "0.8").strip()

# Dynamic SL / Trail
SL_DYNAMIC_ENABLE     = os.getenv("SL_DYNAMIC_ENABLE", "1").lower() in ("1","true","yes","on")
SL_ATR_MULT           = float(os.getenv("SL_ATR_MULT", "0.6"))
SL_TRAIL_ENABLE       = os.getenv("SL_TRAIL_ENABLE", "1").lower() in ("1","true","yes","on")

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
if 'FEAT_QUALITY_ENFORCE' not in globals():
    FEAT_QUALITY_ENFORCE  = os.getenv("FEAT_QUALITY_ENFORCE", "1").lower() in ("1","true","yes","on")
if 'APPROVE_BEFORE_GATE' not in globals():
    APPROVE_BEFORE_GATE   = os.getenv("APPROVE_BEFORE_GATE", "0").lower() in ("1","true","yes","on")

if 'DEFAULT_QTY_STEP' not in globals():
    DEFAULT_QTY_STEP      = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))
if 'DEFAULT_TICK' not in globals():
    DEFAULT_TICK          = float(os.getenv("DEFAULT_PRICE_TICK", "0.01"))
if 'DEFAULT_MIN_NOT' not in globals():
    DEFAULT_MIN_NOT       = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

if 'ORDER_ID_PREFIX' not in globals():
    ORDER_ID_PREFIX             = os.getenv("ORDER_ID_PREFIX", "").strip()
if 'CANCEL_ONLY_PREFIXED_ORDERS' not in globals():
    CANCEL_ONLY_PREFIXED_ORDERS = os.getenv("CANCEL_ONLY_PREFIXED_ORDERS", "0") in ("1","true","yes","on")
if 'CANCEL_PREFIX_OVERRIDE' not in globals():
    CANCEL_PREFIX_OVERRIDE      = os.getenv("CANCEL_PREFIX_OVERRIDE", "").strip()

if 'IDEMPOTENCY_TTL_SEC' not in globals():
    IDEMPOTENCY_TTL_SEC   = int(os.getenv("IDEMPOTENCY_TTL_SEC", "15"))

if 'BOT_TOKEN' not in globals():
    BOT_TOKEN           = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if 'API_BASE' not in globals():
    API_BASE            = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
if 'CONFIRM_TTL_SEC' not in globals():
    CONFIRM_TTL_SEC     = int(os.getenv("CONFIRM_TTL_SEC", "180"))
if 'TELEGRAM_CHAT_ID' not in globals():
    TELEGRAM_CHAT_ID    = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")
if 'TELEGRAM_PARSE_MODE' not in globals():
    TELEGRAM_PARSE_MODE = os.getenv("TELEGRAM_PARSE_MODE", "").strip()

# Redis availability flag
if 'REDIS_URL' not in globals():
    REDIS_URL = os.getenv("REDIS_URL", "").strip()
try:
    import redis  # type: ignore
    _redis_available = bool(REDIS_URL)
except Exception:
    _redis_available = False

if 'LEVERAGE_SYMBOL_CAPS' not in globals():
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
    try:
        return get_symbol_filters(symbol) or {}
    except Exception:
        return {}

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
    if _HEDGE_MODE_OVERRIDE in ("1","true","yes","on","hedge"):
        return True
    if _HEDGE_MODE_OVERRIDE in ("0","false","no","off","oneway"):
        return False
    if _HEDGE_MODE_CACHE is not None:
        return _HEDGE_MODE_CACHE
    try:
        data = get_futures_client().futures_account()
        _HEDGE_MODE_CACHE = bool(data.get("dualSidePosition"))
        return _HEDGE_MODE_CACHE
    except Exception:
        _HEDGE_MODE_CACHE = False
        return False

def _effective_position_side(desired: str) -> str:
    """
    One-Way → נחזיר 'BOTH' (כלומר לא נשלח positionSide בכלל).
    Hedge → נחזיר LONG/SHORT בלבד.
    """
    desired = (desired or "BOTH").upper()
    if not _is_hedge_mode_runtime():
        return "BOTH"
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
    alpha = 1.0/period
    s=None
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
        alpha = 1/p
        out=[]; s=None
        for x in xs:
            s = x if s is None else (alpha*x + (1-alpha)*s)
            out.append(s)
        return out

    if len(tr_list) < period: return 0.0
    tr_rma = rma(tr_list, period)
    pdm_rma = rma(plus_dm, period)
    mdm_rma = rma(minus_dm, period)
    dx=[]
    for t, p, m in zip(tr_rma, pdm_rma, mdm_rma):
        if t <= 0: di_p, di_m = 0.0, 0.0
        else:
            di_p = (p / t) * 100.0
            di_m = (m / t) * 100.0
        denom = (di_p + di_m)
        dx.append(0.0 if denom == 0 else abs(di_p - di_m) / denom * 100.0)
    if not dx: return 0.0
    adx = rma(dx, period)[-1]
    return float(adx or 0.0)

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
def _parse_pct_csv(s: str) -> List[float]:
    out=[]
    for x in (s or "").split(","):
        x=x.strip()
        if not x: continue
        try: out.append(float(x))
        except Exception: continue
    return out

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

def _choose_budget_dynamic(quality: Optional[float], price: float) -> float:
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

# ─────────── Telegram confirm (memory/redis) ───────────
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
        rec = cls.get(cid)
        if not rec: return
        rec["status"] = "approved"; rec["approver"] = int(approver) if str(approver).isdigit() else str(approver)
        cls._save(cid, rec)

    @classmethod
    def reject(cls, cid: str, approver: str = "") -> None:
        rec = cls.get(cid)
        if not rec: return
        rec["status"] = "rejected"; rec["approver"] = int(approver) if str(approver).isdigit() else str(approver)
        cls._save(cid, rec)

    @classmethod
    def flush_all(cls) -> None:
        cls._mem.clear()
        if cls._r:
            try:
                for k in cls._r.scan_iter(match="confirm:*"):
                    cls._r.delete(k)
            except Exception:
                pass
    flush = reset = flush_all

async def send_confirm_request(chat_id: int, title: str, summary_html: str, cid: str) -> Dict[str, Any]:
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN missing"}
    kb = {"inline_keyboard": [[
        {"text": "✅ אישור", "callback_data": f"CONFIRM:APPROVE:{cid}"},
        {"text": "❌ ביטול", "callback_data": f"CONFIRM:REJECT:{cid}"}
    ]]}
    summary_plain = summary_html.replace("<br/>", "\n").replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "")
    if TELEGRAM_PARSE_MODE:
        text = f"<b>{title}</b>\n{summary_html}\n\n<b>CID:</b> <code>{cid}</code>"
    else:
        text = f"{title}\n{summary_plain}\n\nCID: {cid}"

    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
        "reply_markup": kb,
    }
    if TELEGRAM_PARSE_MODE:
        payload["parse_mode"] = TELEGRAM_PARSE_MODE
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(f"{API_BASE}/sendMessage", json=payload)
            try:
                return r.json()
            except Exception:
                return {"ok": r.status_code == 200, "status_code": r.status_code, "text": r.text[:200]}
    except Exception as e:
        log.exception("telegram send failed", extra={"err": str(e)})
        return {"ok": False, "error": str(e)}

async def require_approval(chat_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    cid = ConfirmStore.create(chat_id, payload, ttl=CONFIRM_TTL_SEC)
    title = "אישור טרייד"
    q = payload.get("quality"); bud = payload.get("budget"); lev = payload.get("leverage")
    summary = (
        f"<b>{payload.get('symbol')}</b> {payload.get('side')}  "
        f"qty={payload.get('qty')} lev={lev} budget≈{bud} USDT<br/>"
        f"Quality≈{q} | כניסה: HYBRID (Limit±{ENTRY_BAND_BPS}bps / Stop±{STOP_BAND_BPS}bps)"
    )
    await send_confirm_request(chat_id, title, summary, cid)
    t0 = time.time()
    while time.time() - t0 < CONFIRM_TTL_SEC:
        rec = ConfirmStore.get(cid)
        if rec and rec.get("status") in ("approved", "rejected", "expired"):
            return {"cid": cid, "status": rec["status"]}
        await asyncio.sleep(0.5)
    return {"cid": cid, "status": "expired"}

# ─────────── Cancel old closing orders (TP/SL) ───────────
def _cancel_old_closing_orders(symbol: str) -> int:
    try:
        orders = get_all_orders(symbol, limit=50) or []
        tps = ("TAKE_PROFIT", "TAKE_PROFIT_MARKET")
        sls = ("STOP", "STOP_MARKET")
        pref = (CANCEL_PREFIX_OVERRIDE or ORDER_ID_PREFIX or "").strip()
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
                    plan["tp_orders"].append({"type": "TAKE_PROFIT_MARKET","stopPrice": stop_p,"qty": qalloc})
                else:
                    plan["tp_orders"].append({"type": "TAKE_PROFIT","stopPrice": stop_p,"price": stop_p,"qty": qalloc})
            else:
                plan["sl_orders"].append({"type": "STOP_MARKET","stopPrice": stop_p,"qty": qalloc})

    if tp_targets: _prep("TP", tp_targets, tp_splits, +1 if side=="BUY" else -1)
    if sl_targets: _prep("SL", sl_targets, sl_splits, -1 if side=="BUY" else +1)
    return plan

def _normalize_position_side(ps: Optional[str]) -> str:
    ps = (ps or "BOTH").upper().strip()
    return ps if ps in {"BOTH", "LONG", "SHORT"} else "BOTH"

def _close_side_for(entry_side: str) -> str:
    return "SELL" if entry_side.upper() == "BUY" else "BUY"

def _pos_side_for_entry(side: str) -> str:
    return "LONG" if side.upper() == "BUY" else "SHORT"

# ─────────── Hybrid entry (LIMIT+STOP עם positionSide מותנה) ───────────
async def _place_hybrid_entry(sym: str, side: str, qty: float, base_price: float,
                              ref_entry: Optional[float], position_side: str) -> Dict[str, Any]:
    ref = ref_entry if ref_entry is not None else base_price
    if side == "BUY":
        limit_price = _offset_bps(ref, -ENTRY_BAND_BPS, +1)
        stop_price  = _offset_bps(ref, +STOP_BAND_BPS,  +1)
    else:
        limit_price = _offset_bps(ref, +ENTRY_BAND_BPS, +1)
        stop_price  = _offset_bps(ref, -STOP_BAND_BPS,  +1)

    cur = get_price(sym) or futures_mark_price(sym) or base_price
    slip_bps_now = abs(cur - ref) / max(ref, 1e-9) * 10000.0
    if slip_bps_now >= SLIPPAGE_GUARD_BPS:
        return {"ok": False, "reason": "slippage_guard", "slip_bps": slip_bps_now}

    limit_str, limit_p = _q_price(sym, float(limit_price))
    stop_str , stop_p  = _q_price(sym, float(stop_price))
    qty_str  , _       = _q_qty(sym, qty)

    eff_ps = _effective_position_side(position_side)

    entry_kwargs = dict(
        symbol=sym, side=side, type="LIMIT",
        timeInForce="GTC", price=limit_str, quantity=qty_str,
        reduceOnly=False
    )
    if eff_ps != "BOTH":
        entry_kwargs["positionSide"] = eff_ps
    lim = futures_create_order(**entry_kwargs)
    lim_id = str(lim.get("orderId") or "")

    stop_kwargs = dict(
        symbol=sym, side=side, type="STOP",
        timeInForce="GTC", stopPrice=stop_str, price=stop_str, quantity=qty_str,
        reduceOnly=False, workingType="MARK_PRICE"
    )
    if eff_ps != "BOTH":
        stop_kwargs["positionSide"] = eff_ps
    stp = futures_create_order(**stop_kwargs)
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
                mkt_kwargs = dict(symbol=sym, side=side, type="MARKET", quantity=qty_str, reduceOnly=False)
                if eff_ps != "BOTH":
                    mkt_kwargs["positionSide"] = eff_ps
                mkt = futures_create_order(**mkt_kwargs)
                mk = get_price(sym) or futures_mark_price(sym) or cur
                bps = abs((cur or 0) - (mk or 0)) / max(mk or 1e-9, 1e-9) * 10000.0 if mk and cur else None
                return {"ok": True, "entry_kind": "MARKET_ESCALATE", "price": float(cur), "sanity_bps": bps, "sanity_ok": (bps is None) or (bps <= POST_FILL_SANITY_BPS), "order": mkt}
            t0 = time.time()
        await asyncio.sleep(1.0)

# ─────────── Public API ───────────
def _compute_tp_sl_targets(side: str, anchor: float, kl: Optional[List[List[float]]]) -> Tuple[Optional[List[float]], Optional[List[float]], Optional[List[float]]]:
    tp_targets: Optional[List[float]] = None
    tp_splits : Optional[List[float]] = None
    sl_targets: Optional[List[float]] = None

    if LADDER_TP_ENABLE:
        try:
            tps = [float(x) for x in _parse_csv_floats(LADDER_TP_DEFAULT_PCTS)]
            sign = +1 if side=="BUY" else -1
            tp_targets = [anchor * (1.0 + sign * p/100.0) for p in tps]
            tp_splits = [float(x) for x in _parse_csv_floats(LADDER_TP_DEFAULT_SPLITS)] or None
        except Exception:
            pass

    if SL_DYNAMIC_ENABLE and kl:
        try:
            atr = _atr_from_klines(kl, 14)
            sign = -1 if side=="BUY" else +1
            sl_p = anchor * (1.0 + sign * ((atr / max(anchor, 1e-9)) * SL_ATR_MULT * 100.0) / 100.0)
            sl_targets = [sl_p]
        except Exception:
            sl_targets = None

    if (not sl_targets) and LADDER_SL_ENABLE:
        try:
            src = LADDER_SL_DEFAULT_PCTS if LADDER_SL_DEFAULT_PCTS else "0.8"
            slps = [float(x) for x in _parse_csv_floats(src)]
            sign = -1 if side=="BUY" else +1
            sl_targets = [anchor * (1.0 + sign * p/100.0) for p in slps]
        except Exception:
            sl_targets = None

    return tp_targets, tp_splits, sl_targets

async def execute_trade_live(
    symbol: str, side: str, *,
    budget: Optional[float] = None, leverage: int = 5, dry_run: bool = True,
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
    position_side = _normalize_position_side(position_side)
    position_side = _effective_position_side(position_side)  # התאמה אוטו׳ ל-Hedge/One-Way

    base_price = get_price(sym) or futures_mark_price(sym)
    if not base_price or base_price <= 0:
        raise RuntimeError(f"Cannot fetch price for {sym}")

    ref_for_guard = float(entry or base_price)
    mk = float(get_price(sym) or futures_mark_price(sym) or base_price)
    pp_bps = abs(mk - ref_for_guard) / max(ref_for_guard, 1e-9) * 10000.0
    if pp_bps >= PERCENT_PRICE_GUARD_BPS:
        return {"ok": False, "reason": "percent_price_guard", "bps": pp_bps, "mk": mk, "ref": ref_for_guard}

    gate = _quality_gate(sym, side)
    try:
        score_for_budget: Optional[float] = float(gate.get("score")) if gate.get("score") is not None else QUALITY_DEFAULT
    except Exception:
        score_for_budget = QUALITY_DEFAULT

    try:
        kl = _fetch_klines_raw(sym, "1m", 60)
        atr_for_budget: Optional[float] = _atr_from_klines(kl, 14) if kl else None
        adx_for_lev: float = _adx_from_klines(kl, 14) if kl else 0.0
    except Exception:
        atr_for_budget = None
        adx_for_lev = 0.0
        kl = None

    dyn_leverage = _choose_leverage(sym, adx_for_lev, leverage)

    if BUDGET_DYNAMIC_ENABLE and (budget is None or float(budget) <= 0):
        budget = _choose_budget_dynamic(score_for_budget, float(base_price))

    qty_calc_error = None
    qty: Optional[float] = None
    try:
        qty = _calc_qty(sym, float(base_price), budget, dyn_leverage, quantity)
    except Exception as e:
        qty_calc_error = str(e)

    risk = pre_trade_risk_check(sym, side, dyn_leverage, entry)

    idem_payload = {"sym": sym, "side": side, "lev": int(dyn_leverage),
                    "qty": round(float(qty or 0), 10), "dry": bool(dry_run),
                    "entry_bucket": round(ref_for_guard, 5)}
    if not _Idem.check_and_set(idem_payload, ttl=IDEMPOTENCY_TTL_SEC):
        return {"ok": False, "reason": "idem_conflict", "ttl_sec": IDEMPOTENCY_TTL_SEC}

    if (tp is None and not tp_targets) or (sl is None and not sl_targets):
        tps, tps_splits, sls = _compute_tp_sl_targets(side, float(entry or base_price), kl)
        if tp is None and not tp_targets: tp_targets, tp_splits = tps, tps_splits
        if sl is None and not sl_targets: sl_targets = sls

    if REQUIRE_TP_AND_SL:
        if not (tp_targets or tp is not None):
            return {"ok": False, "reason": "tp_required"}
        if not (sl_targets or sl is not None):
            return {"ok": False, "reason": "sl_required"}

    if dry_run:
        plan: Dict[str, Any] = {
            "ok": True, "symbol": sym, "side": side, "leverage": dyn_leverage,
            "base_price": float(base_price), "dry_run": True,
            "entry_policy": f"HYBRID_LIMIT_STOP({ENTRY_BAND_BPS}/{STOP_BAND_BPS}bps)+MARKET_ESCALATION",
            "gate": gate, "risk": risk, "alloc_ok": qty is not None, "alloc_error": qty_calc_error,
            "guards": {"percent_price_bps": pp_bps, "slippage_guard_bps": SLIPPAGE_GUARD_BPS},
            "position_side": position_side, "reduce_only": reduce_only,
            "budget_used": float(budget or 0.0), "quality": score_for_budget,
            "adx": adx_for_lev,
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

    must_approve = True if ENFORCE_APPROVAL_ALWAYS else bool(confirm_first)
    if must_approve:
        chat_id = int(telegram_chat_id or TELEGRAM_CHAT_ID or 0)
        if not chat_id:
            return {"ok": False, "reason": "telegram_chat_id_required"}
        payload = {"symbol": sym, "side": side, "qty": qty, "leverage": dyn_leverage, "quality": score_for_budget, "budget": float(budget or 0.0)}
        if APPROVE_BEFORE_GATE:
            approval = await require_approval(chat_id, payload)
            if approval.get("status") != "approved":
                return {"ok": False, "status": approval.get("status"), "reason": "not_approved"}

    if FEAT_QUALITY_ENFORCE and not gate.get("enter_ok"):
        return {"ok": False, "reason": "quality_gate_rejected", "gate": gate}

    if must_approve and not APPROVE_BEFORE_GATE:
        chat_id = int(telegram_chat_id or TELEGRAM_CHAT_ID or 0)
        if not chat_id:
            return {"ok": False, "reason": "telegram_chat_id_required"}
        payload = {"symbol": sym, "side": side, "qty": qty, "leverage": dyn_leverage, "quality": score_for_budget, "budget": float(budget or 0.0)}
        approval = await require_approval(chat_id, payload)
        if approval.get("status") != "approved":
            return {"ok": False, "status": approval.get("status"), "reason": "not_approved"}

    _cancel_old_closing_orders(sym)

    try:
        set_leverage(sym, int(dyn_leverage))
    except Exception as e:
        log.warning("set_leverage failed: %s", e)

    entry_res = await _place_hybrid_entry(sym, side, qty, float(base_price), entry, position_side)
    if not entry_res or (entry_res.get("ok") is False):
        return {"ok": False, "reason": entry_res.get("reason", "entry_failed"), "details": entry_res}

    sanity_ok = bool(entry_res.get("sanity_ok", True))
    sanity_bps = entry_res.get("sanity_bps")

    plan: Dict[str, Any] = {
        "ok": True, "symbol": sym, "side": side, "qty": qty, "leverage": dyn_leverage,
        "base_price": float(base_price), "dry_run": False,
        "entry_policy": f"HYBRID_LIMIT_STOP({ENTRY_BAND_BPS}/{STOP_BAND_BPS}bps)+MARKET_ESCALATION",
        "gate": gate, "risk": risk, "entry_result": entry_res,
        "tp_orders": [], "sl_orders": [],
        "sanity_ok": sanity_ok, "sanity_bps": sanity_bps,
        "position_side": position_side, "reduce_only": reduce_only,
        "budget_used": float(budget or 0.0), "quality": score_for_budget,
        "adx": adx_for_lev,
    }

    close_side = _close_side_for(side)
    ladders = _build_ladders(sym, side, qty,
                             ([tp] if tp is not None else tp_targets), tp_splits,
                             ([sl] if sl is not None else sl_targets), sl_splits)
    plan["tp_orders"] = ladders["tp_orders"]; plan["sl_orders"] = ladders["sl_orders"]

    def _place_with_retry(args: Dict[str, Any]) -> Dict[str, Any]:
        """שולח הזמנה, ואם קיבלנו -1106 על reduceOnly – מנסה שוב בלי reduceOnly."""
        try:
            return futures_create_order(**args)
        except Exception as e:
            msg = str(e).lower()
            if "reduceonly" in msg or "reduce only" in msg:
                a2 = dict(args)
                a2.pop("reduceOnly", None)
                return futures_create_order(**a2)
            raise

    tp_success = False
    sl_success = False
    for arr in (plan["tp_orders"], plan["sl_orders"]):
        for o in arr:
            typ = str(o.get("type")).upper()
            args: Dict[str, Any] = dict(
                symbol=sym,
                side=close_side,
                type=typ,
                workingType="MARK_PRICE",
            )

            eff_ps = _effective_position_side(position_side)
            if eff_ps != "BOTH":
                args["positionSide"] = eff_ps  # Hedge: LONG/SHORT

            # MARKET-trigger (STOP_MARKET/TAKE_PROFIT_MARKET) – לא שולחים TIF/price
            if "MARKET" in typ:
                args["stopPrice"] = _q_price(sym, float(o["stopPrice"]))[0]
            else:
                args["stopPrice"] = _q_price(sym, float(o["stopPrice"]))[0]
                args["price"]     = _q_price(sym, float(o.get("price", o["stopPrice"])))[0]
                args["timeInForce"] = "GTC"

            args["quantity"] = _q_qty(sym, float(o["qty"]))[0]

            # ⚠️ One-Way + MARKET trigger → אל תשלח reduceOnly (ימנע -1106)
            is_market_trigger = typ in ("STOP_MARKET", "TAKE_PROFIT_MARKET")
            if not (is_market_trigger and eff_ps == "BOTH"):
                args["reduceOnly"] = True

            try:
                resp = _place_with_retry(args)
                o["response"] = resp
                if typ.startswith("TAKE_PROFIT"):
                    tp_success = tp_success or bool(resp.get("orderId"))
                if typ.startswith("STOP"):
                    sl_success = sl_success or bool(resp.get("orderId"))
            except Exception as e:
                o["response"] = {"ok": False, "error": str(e)}

    if REQUIRE_TP_AND_SL and not (tp_success and sl_success):
        rb = _safe_close_position(sym, side, qty, position_side=position_side)
        plan.update({
            "ok": False,
            "reason": "tp_sl_arming_failed",
            "rolled_back": True,
            "rollback": rb,
        })
        return plan

    return plan

# ─────────── Helpers (rollback) ───────────
def _safe_close_position(sym: str, side: str, qty: float, position_side: str = "BOTH") -> Dict[str, Any]:
    eff_ps = _effective_position_side(_normalize_position_side(position_side))
    close_side = _close_side_for(side)
    args = dict(
        symbol=sym,
        side=close_side,
        type="MARKET",
        quantity=_q_qty(sym, qty)[0],
    )
    if eff_ps != "BOTH":
        args["positionSide"] = eff_ps
        args["reduceOnly"] = True  # Hedge תקין
    try:
        return {"ok": True, "response": futures_create_order(**args)}
    except Exception as e:
        msg = str(e).lower()
        if "reduceonly" in msg or "reduce only" in msg:
            args2 = dict(args); args2.pop("reduceOnly", None)
            try:
                return {"ok": True, "response": futures_create_order(**args2)}
            except Exception as e2:
                return {"ok": False, "error": str(e2)}
        return {"ok": False, "error": str(e)}

__all__ = [
    "execute_trade_live",
    "ConfirmStore",
    "send_confirm_request",
    "require_approval",
]


























































































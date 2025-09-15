# utils/trade_executor.py
from __future__ import annotations
import os, math, time, logging, asyncio, json, hashlib
from typing import Optional, Dict, Any, List, Tuple

import httpx

from utils.binance_client import (
    get_price, futures_mark_price, set_leverage, futures_create_order,
    get_symbol_filters, get_all_orders, futures_cancel_order, get_futures_client
)

# ✅ Dynamic budget (גלובלי) — נופל ל-MAX_TRADE_BUDGET אם כבוי/חסר
try:
    from utils.budget import get_budget_usdt  # דינמי אם DYNAMIC_BUDGET_ENABLE=1
except Exception:
    def get_budget_usdt(symbol: Optional[str] = None, *, quality: Optional[float] = None,
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

# Limit offsets (כשמשתמשים ב-LIMIT ל-TP)
SL_LIMIT_OFFSET_BPS   = float(os.getenv("SL_LIMIT_OFFSET_BPS", "8"))
TP_LIMIT_OFFSET_BPS   = float(os.getenv("TP_LIMIT_OFFSET_BPS", "8"))

# Gate/Quality
MIN_QUALITY_SCORE     = float(os.getenv("MIN_QUALITY_SCORE", "8.5"))
MAX_ATR_PCT           = float(os.getenv("MAX_ATR_PCT", "2.5"))
MIN_VOLUME            = float(os.getenv("MIN_VOLUME", "0"))

# Env flags
FEAT_QUALITY_ENFORCE  = os.getenv("FEAT_QUALITY_ENFORCE", "1").lower() in ("1","true","yes","on")
APPROVE_BEFORE_GATE   = os.getenv("APPROVE_BEFORE_GATE", "0").lower() in ("1","true","yes","on")

# 🔒 Always require Telegram approval + require TP&SL
ENFORCE_APPROVAL_ALWAYS  = os.getenv("ENFORCE_APPROVAL_ALWAYS", "1").lower() in ("1","true","yes","on")
REQUIRE_TP_AND_SL        = os.getenv("REQUIRE_TP_AND_SL", "1").lower() in ("1","true","yes","on")

DEFAULT_QTY_STEP      = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))
DEFAULT_TICK          = float(os.getenv("DEFAULT_PRICE_TICK", "0.01"))
DEFAULT_MIN_NOT       = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

# Ladder config
LADDER_TP_ENABLE          = os.getenv("LADDER_TP_ENABLE", "1") in ("1","true","yes","on")
LADDER_TP_KIND            = os.getenv("LADDER_TP_KIND", "TAKE_PROFIT_MARKET").upper()  # TAKE_PROFIT or TAKE_PROFIT_MARKET
LADDER_TP_DEFAULT_PCTS    = os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5")
LADDER_TP_DEFAULT_SPLITS  = os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25")
LADDER_SL_ENABLE          = os.getenv("LADDER_SL_ENABLE", "1") in ("1","true","yes","on")  # ← ON by default
LADDER_SL_DEFAULT_PCTS    = os.getenv("LADDER_SL_DEFAULT_PCTS", "0.8").strip()             # ← default 0.8% כדי שתמיד יהיה SL
TP_LADDER_COOLDOWN_SEC    = int(os.getenv("TP_LADDER_COOLDOWN_SEC", "60"))

# Idempotency
IDEMPOTENCY_TTL_SEC   = int(os.getenv("IDEMPOTENCY_TTL_SEC", "15"))

# Prefix controls for cancels
ORDER_ID_PREFIX             = os.getenv("ORDER_ID_PREFIX", "").strip()
CANCEL_ONLY_PREFIXED_ORDERS = os.getenv("CANCEL_ONLY_PREFIXED_ORDERS", "0") in ("1","true","yes","on")
CANCEL_PREFIX_OVERRIDE      = os.getenv("CANCEL_PREFIX_OVERRIDE", "").strip()

# Telegram
BOT_TOKEN           = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE            = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
CONFIRM_TTL_SEC     = int(os.getenv("CONFIRM_TTL_SEC", "180"))
TELEGRAM_CHAT_ID    = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")
TELEGRAM_PARSE_MODE = os.getenv("TELEGRAM_PARSE_MODE", "").strip()  # "" (ברירת מחדל), או "HTML"/"MarkdownV2"

# Redis (אופציונלי) — Idempotency/ConfirmStore
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
    try:
        f = get_symbol_filters(symbol) or {}
    except Exception:
        f = {}
    return f

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
        rec = cls.get(cid)
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
    # טקסט שמתאים גם בלי parse_mode
    summary_plain = (
        summary_html.replace("<br/>", "\n")
                    .replace("<b>", "").replace("</b>", "")
                    .replace("<code>", "").replace("</code>", "")
    )
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

# ─────────── Ladders build (SL כ-STOP_MARKET, workingType ב-שליחה) ───────────
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
            else:
                # ⛔️ SL תמיד כ־STOP_MARKET (ללא price)
                plan["sl_orders"].append({
                    "type": "STOP_MARKET",
                    "stopPrice": stop_p,
                    "qty": qalloc,
                })

    if tp_targets: _prep("TP", tp_targets, tp_splits, +1 if side=="BUY" else -1)
    if sl_targets: _prep("SL", sl_targets, sl_splits, -1 if side=="BUY" else +1)
    return plan

# ─────────── Hybrid entry + escalation ───────────
async def _place_hybrid_entry(sym: str, side: str, qty: float, base_price: float, ref_entry: Optional[float]) -> Dict[str, Any]:
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

    lim = futures_create_order(symbol=sym, side=side, type="LIMIT",
                               timeInForce="GTC", price=limit_str, quantity=qty_str)
    lim_id = str(lim.get("orderId") or "")
    stp = futures_create_order(symbol=sym, side=side, type="STOP",
                               timeInForce="GTC", stopPrice=stop_str, price=stop_str, quantity=qty_str)
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
                mkt = futures_create_order(symbol=sym, side=side, type="MARKET", quantity=qty_str)
                mk = get_price(sym) or futures_mark_price(sym) or cur
                bps = abs((cur or 0) - (mk or 0)) / max(mk or 1e-9, 1e-9) * 10000.0 if mk and cur else None
                return {"ok": True, "entry_kind": "MARKET_ESCALATE", "price": float(cur), "sanity_bps": bps, "sanity_ok": (bps is None) or (bps <= POST_FILL_SANITY_BPS), "order": mkt}
            t0 = time.time()
        await asyncio.sleep(1.0)

# ─────────── Helpers ───────────
def _has_order_id(resp: Dict[str, Any]) -> bool:
    try:
        return bool(resp and resp.get("orderId"))
    except Exception:
        return False

def _q_or_none(sym: str, v: Optional[float]) -> Optional[str]:
    if v is None: return None
    return _q_price(sym, float(v))[0]

def _qty_or_none(sym: str, v: Optional[float]) -> Optional[str]:
    if v is None: return None
    return _q_qty(sym, float(v))[0]

def _opposite_side(side: str) -> str:
    return "SELL" if side.upper() == "BUY" else "BUY"

def _now_ms() -> int:
    return int(time.time()*1000)

def _safe_close_position(sym: str, side: str, qty: float) -> Dict[str, Any]:
    """Try to immediately flat the just-opened position if we failed to arm TP/SL."""
    close_side = _opposite_side(side)
    try:
        resp = futures_create_order(
            symbol=sym, side=close_side, type="MARKET",
            reduceOnly=True, timeInForce="GTC",
            quantity=_q_qty(sym, qty)[0]
        )
        return {"ok": True, "response": resp}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─────────── Public API ───────────
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

    base_price = get_price(sym) or futures_mark_price(sym)
    if not base_price or base_price <= 0:
        raise RuntimeError(f"Cannot fetch price for {sym}")

    # Percent-Price Guard
    ref_for_guard = float(entry or base_price)
    mk = float(get_price(sym) or futures_mark_price(sym) or base_price)
    pp_bps = abs(mk - ref_for_guard) / max(ref_for_guard, 1e-9) * 10000.0
    if pp_bps >= PERCENT_PRICE_GUARD_BPS:
        return {"ok": False, "reason": "percent_price_guard", "bps": pp_bps, "mk": mk, "ref": ref_for_guard}

    # איכות/ATR — לצורך תקציב דינמי
    gate = _quality_gate(sym, side)
    try:
        score_for_budget: Optional[float] = float(gate.get("score")) if gate.get("score") is not None else None
    except Exception:
        score_for_budget = None

    try:
        kl = _fetch_klines_raw(sym, "1m", 60)
        atr_for_budget: Optional[float] = _atr_from_klines(kl, 14) if kl else None
    except Exception:
        atr_for_budget = None

    # תקציב
    if budget is None or float(budget) <= 0:
        budget = get_budget_usdt(symbol=sym, quality=score_for_budget, atr=atr_for_budget, price=float(base_price))

    # חישוב כמות
    qty_calc_error = None
    qty: Optional[float] = None
    try:
        qty = _calc_qty(sym, float(base_price), budget, leverage, quantity)
    except Exception as e:
        qty_calc_error = str(e)

    # ✅ Risk preview
    risk = pre_trade_risk_check(sym, side, leverage, entry)

    # Idempotency Shield
    idem_payload = {"sym": sym, "side": side, "lev": int(leverage),
                    "qty": round(float(qty or 0), 10), "dry": bool(dry_run),
                    "entry_bucket": round(ref_for_guard, 5)}
    if not _Idem.check_and_set(idem_payload, ttl=IDEMPOTENCY_TTL_SEC):
        return {"ok": False, "reason": "idem_conflict", "ttl_sec": IDEMPOTENCY_TTL_SEC}

    # הרחבת TP/SL מה-ENV אם לא הגיעו
    if tp is None and not tp_targets and LADDER_TP_ENABLE:
        try:
            tps = [float(x) for x in _parse_csv_floats(LADDER_TP_DEFAULT_PCTS)]
            anchor = float(entry or base_price); sign = +1 if side=="BUY" else -1
            tp_targets = [anchor * (1.0 + sign * p/100.0) for p in tps]
            tp_splits = [float(x) for x in _parse_csv_floats(LADDER_TP_DEFAULT_SPLITS)] or None
        except Exception:
            pass
    if sl is None and not sl_targets and LADDER_SL_ENABLE:
        try:
            slps_src = LADDER_SL_DEFAULT_PCTS if LADDER_SL_DEFAULT_PCTS else "0.8"
            slps = [float(x) for x in _parse_csv_floats(slps_src)]
            anchor = float(entry or base_price); sign = -1 if side=="BUY" else +1
            sl_targets = [anchor * (1.0 + sign * p/100.0) for p in slps]
        except Exception:
            pass

    # 🔒 חובה TP + SL לפני המשך (אלא אם REQUIRE_TP_AND_SL=0)
    if REQUIRE_TP_AND_SL:
        if not (tp_targets or tp is not None):
            return {"ok": False, "reason": "tp_required"}
        if not (sl_targets or sl is not None):
            return {"ok": False, "reason": "sl_required"}

    # DRY-RUN: מחזיר תוכנית בלבד
    if dry_run:
        plan: Dict[str, Any] = {
            "ok": True, "symbol": sym, "side": side, "leverage": leverage,
            "base_price": float(base_price), "dry_run": True,
            "entry_policy": f"HYBRID_LIMIT_STOP({ENTRY_BAND_BPS}/{STOP_BAND_BPS}bps)+MARKET_ESCALATION",
            "gate": gate, "risk": risk, "alloc_ok": qty is not None, "alloc_error": qty_calc_error,
            "guards": {"percent_price_bps": pp_bps, "slippage_guard_bps": SLIPPAGE_GUARD_BPS},
            "position_side": position_side, "reduce_only": reduce_only,
            "budget_used": float(budget or 0.0),
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

    # שגיאת כמות?
    if qty is None:
        return {"ok": False, "reason": qty_calc_error or "allocation_invalid"}

    # 🔒 אישור טלגרם — תמיד
    must_approve = True if ENFORCE_APPROVAL_ALWAYS else bool(confirm_first)
    if must_approve:
        chat_id = int(telegram_chat_id or TELEGRAM_CHAT_ID or 0)
        if not chat_id:
            return {"ok": False, "reason": "telegram_chat_id_required"}
        # שלב אישור בהתאם לדגל הישן (ברירת מחדל: אחרי Gate)
        if APPROVE_BEFORE_GATE:
            approval = await require_approval(chat_id, {"symbol": sym, "side": side, "qty": qty, "leverage": leverage})
            if approval.get("status") != "approved":
                return {"ok": False, "status": approval.get("status"), "reason": "not_approved"}

    # Gate – אכיפה תלויה דגל
    if FEAT_QUALITY_ENFORCE and not gate.get("enter_ok"):
        return {"ok": False, "reason": "quality_gate_rejected", "gate": gate}

    # אישור אחרי Gate (ברירת מחדל)
    if must_approve and not APPROVE_BEFORE_GATE:
        chat_id = int(telegram_chat_id or TELEGRAM_CHAT_ID or 0)
        if not chat_id:
            return {"ok": False, "reason": "telegram_chat_id_required"}
        approval = await require_approval(chat_id, {"symbol": sym, "side": side, "qty": qty, "leverage": leverage})
        if approval.get("status") != "approved":
            return {"ok": False, "status": approval.get("status"), "reason": "not_approved"}

    # Hygiene: בטל TP/SL קודמים
    _cancel_old_closing_orders(sym)

    try:
        set_leverage(sym, int(leverage))
    except Exception as e:
        log.warning("set_leverage failed: %s", e)

    entry_res = await _place_hybrid_entry(sym, side, qty, float(base_price), entry)
    if not entry_res or (entry_res.get("ok") is False):
        return {"ok": False, "reason": entry_res.get("reason", "entry_failed"), "details": entry_res}

    sanity_ok = bool(entry_res.get("sanity_ok", True))
    sanity_bps = entry_res.get("sanity_bps")

    plan: Dict[str, Any] = {
        "ok": True, "symbol": sym, "side": side, "qty": qty, "leverage": leverage,
        "base_price": float(base_price), "dry_run": False,
        "entry_policy": f"HYBRID_LIMIT_STOP({ENTRY_BAND_BPS}/{STOP_BAND_BPS}bps)+MARKET_ESCALATION",
        "gate": gate, "risk": risk, "entry_result": entry_res,
        "tp_orders": [], "sl_orders": [],
        "sanity_ok": sanity_ok, "sanity_bps": sanity_bps,
        "position_side": position_side, "reduce_only": reduce_only,
        "budget_used": float(budget or 0.0),
    }

    close_side = _opposite_side(side)
    ladders = _build_ladders(sym, side, qty,
                             ([tp] if tp is not None else tp_targets), tp_splits,
                             ([sl] if sl is not None else sl_targets), sl_splits)
    plan["tp_orders"] = ladders["tp_orders"]; plan["sl_orders"] = ladders["sl_orders"]

    # שליחת TP/SL עם ReduceOnly + workingType=MARK_PRICE
    tp_success = False
    sl_success = False
    for arr in (plan["tp_orders"], plan["sl_orders"]):
        for o in arr:
            typ = str(o.get("type")).upper()
            args: Dict[str, Any] = dict(
                symbol=sym,
                side=close_side,
                type=typ,
                reduceOnly=True,
                timeInForce="GTC",
                workingType="MARK_PRICE",  # ← הטריגר מול Mark Price
            )
            if "MARKET" in typ:
                args["stopPrice"] = _q_price(sym, float(o["stopPrice"]))[0]
            else:
                args["stopPrice"] = _q_price(sym, float(o["stopPrice"]))[0]
                args["price"]     = _q_price(sym, float(o.get("price", o["stopPrice"])))[0]

            args["quantity"] = _q_qty(sym, float(o["qty"]))[0]

            try:
                resp = futures_create_order(**args)
                o["response"] = resp
                if typ.startswith("TAKE_PROFIT"):
                    tp_success = tp_success or _has_order_id(resp)
                if typ.startswith("STOP"):
                    sl_success = sl_success or _has_order_id(resp)
            except Exception as e:
                o["response"] = {"ok": False, "error": str(e)}

    # 🔒 אם אין גם TP וגם SL מוצלחים — נסגור מיידית את הפוזיציה
    if REQUIRE_TP_AND_SL and not (tp_success and sl_success):
        rb = _safe_close_position(sym, side, qty)
        plan.update({
            "ok": False,
            "reason": "tp_sl_arming_failed",
            "rolled_back": True,
            "rollback": rb,
        })
        # נסמן שניסינו, ונחזיר את התוכנית כולל שגיאות ההצבה
        return plan

    return plan














































































from __future__ import annotations
import os, math, time, logging, asyncio, json
from typing import Optional, Dict, Any, List, Tuple

import httpx

from utils.binance_client import (
    get_price, futures_mark_price, set_leverage, futures_create_order,
    get_symbol_filters, get_all_orders, futures_cancel_order, get_futures_client
)

log = logging.getLogger("algogpt.trade_executor")

# ─────────── Policy & Defaults (ENV) ───────────
ALLOW_MARKET_ENTRY = os.getenv("ALLOW_MARKET_ENTRY", "1") in ("1","true","yes","on")

# כניסה היברידית: LIMIT Maker סביב המחיר + STOP (breakout) בצד השני
ENTRY_BAND_BPS   = float(os.getenv("ENTRY_BAND_BPS", "8.5"))   # ★ ברירת מחדל עודכנה ל־8.5bps
STOP_BAND_BPS    = float(os.getenv("STOP_BAND_BPS",  "10"))
ESCALATE_AFTER_S = float(os.getenv("ESCALATE_AFTER_SEC", "10"))
ESCALATE_SLIP_BPS= float(os.getenv("ESCALATE_SLIPPAGE_BPS", "15"))

# דיוק SL/TP (limit-variants)
SL_LIMIT_OFFSET_BPS = float(os.getenv("SL_LIMIT_OFFSET_BPS", "8"))
TP_LIMIT_OFFSET_BPS = float(os.getenv("TP_LIMIT_OFFSET_BPS", "8"))

# איכות סיגנל (Gate)
MIN_QUALITY_SCORE = float(os.getenv("MIN_QUALITY_SCORE", "6"))
MAX_ATR_PCT       = float(os.getenv("MAX_ATR_PCT", "2.5"))  # ATR(14) כאחוז מחיר
MIN_VOLUME        = float(os.getenv("MIN_VOLUME", "0"))     # אם 0 -> מתעלמים

# דיוקים כלליים
DEFAULT_QTY_STEP = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))
DEFAULT_TICK     = float(os.getenv("DEFAULT_PRICE_TICK", "0.01"))
DEFAULT_MIN_NOT  = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

# Telegram
BOT_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE        = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
CONFIRM_TTL_SEC = int(os.getenv("CONFIRM_TTL_SEC", "180"))

# Redis (אופציונלי)
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
    s = f"{p:.{decs}f}"
    return s, float(s)

def _q_qty(symbol: str, qty: float) -> Tuple[str, float]:
    f = _filters(symbol); step = float(f.get("stepSize") or DEFAULT_QTY_STEP) or DEFAULT_QTY_STEP
    decs = _decimals(str(f.get("stepSize") or DEFAULT_QTY_STEP))
    steps = math.floor(qty / step); q = max(step, steps * step)
    s = f"{q:.{decs}f}"
    return s, float(s)

def _min_notional(symbol: str) -> float:
    f = _filters(symbol); mn = f.get("minNotional")
    try: return float(mn) if mn is not None else DEFAULT_MIN_NOT
    except Exception: return DEFAULT_MIN_NOT

def _ensure_min_notional(symbol: str, price: float, qty: float) -> float:
    mn = _min_notional(symbol)
    if price * qty >= mn: return qty
    need = mn / max(price, 1e-9)
    _, q2 = _q_qty(symbol, need)
    return q2

def _calc_qty(symbol: str, price: float, budget: Optional[float], leverage: int, quantity: Optional[float]) -> float:
    if quantity and quantity > 0:
        q = float(quantity)
    else:
        if not budget or budget <= 0: raise ValueError("Either positive budget or quantity must be provided")
        usd = float(budget) * float(leverage)
        q = usd / price
    q = _ensure_min_notional(symbol, price, q)
    _, q = _q_qty(symbol, q)
    return q

def _offset_bps(base: float, bps: float, sign: int) -> float:
    return base * (1.0 + sign * (bps / 10000.0))

# ─────────── Telegram Confirm Store (memory/redis) ───────────
class ConfirmStore:
    _mem: Dict[str, Dict[str, Any]] = {}  # cid -> record
    _r = None
    try:
        if _redis_available:
            _r = redis.Redis.from_url(REDIS_URL, decode_responses=True)  # type: ignore
    except Exception as e:
        log.warning("Redis unavailable: %s", e)
        _r = None

    @classmethod
    def create(cls, chat_id: int, payload: Dict[str, Any], ttl: int = CONFIRM_TTL_SEC) -> str:
        cid = f"cid_{int(time.time()*1000)}_{os.getpid()}_{abs(hash(os.urandom(8)))}"
        rec = {"status": "pending", "payload": payload, "chat_id": chat_id, "created_at": time.time()}
        if cls._r:
            cls._r.setex(f"confirm:{cid}", ttl, json.dumps(rec))
        else:
            cls._mem[cid] = rec
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
            if cls._r:
                cls._r.setex(f"confirm:{cid}", 60, json.dumps(rec))
            else:
                cls._mem[cid] = rec
        return rec

    @classmethod
    def _save(cls, cid: str, rec: Dict[str, Any]) -> None:
        if cls._r:
            cls._r.setex(f"confirm:{cid}", 60, json.dumps(rec))
        else:
            cls._mem[cid] = rec

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
    kb = {
        "inline_keyboard": [[
            {"text": "✅ אישור", "callback_data": f"CONFIRM:APPROVE:{cid}"},
            {"text": "❌ ביטול", "callback_data": f"CONFIRM:REJECT:{cid}"}
        ]]
    }
    text = f"<b>{title}</b>\n{summary_html}\n\n<b>CID:</b> <code>{cid}</code>"
    async with httpx.AsyncClient(timeout=10.0) as cli:
        r = await cli.post(f"{API_BASE}/sendMessage", data={
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True, "reply_markup": json.dumps(kb)
        })
        try:
            return r.json()
        except Exception:
            return {"ok": False, "error": f"http {r.status_code}"}

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
    k = 2 / (period + 1)
    ema = []
    s = None
    for v in vals:
        if s is None: s = v
        else: s = v * k + s * (1 - k)
        ema.append(s)
    return ema

def _atr_from_klines(kl: List[List[float]], period: int = 14) -> float:
    # kline: [open_time, open, high, low, close, volume, ...]
    trs: List[float] = []
    prev_close = None
    for row in kl:
        high = float(row[2]); low = float(row[3]); close = float(row[4])
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = close
    if len(trs) < period: return trs[-1] if trs else 0.0
    # EMA-ATR
    return _ema(trs, period)[-1]

def _fetch_klines_raw(symbol: str, interval: str = "1m", limit: int = 50) -> List[List[float]]:
    cli = get_futures_client()
    data = cli.futures_klines(symbol=symbol.upper(), interval=interval, limit=min(1000, max(10, limit)))
    return data or []

def _quality_gate(symbol: str, side: str) -> Dict[str, Any]:
    """Computes Quality Score 0..10; enter only if score >= MIN_QUALITY_SCORE."""
    try:
        kl = _fetch_klines_raw(symbol, "1m", 60)
        closes = [float(r[4]) for r in kl]
        highs  = [float(r[2]) for r in kl]
        lows   = [float(r[3]) for r in kl]
        vols   = [float(r[5]) for r in kl]
        if len(closes) < 30:
            return {"enter_ok": False, "score": 0.0, "reasons": ["insufficient_data"]}

        ema21 = _ema(closes, 21)[-1]
        ema50 = _ema(closes, 50)[-1]
        last  = closes[-1]
        atr   = _atr_from_klines(kl, 14)
        atr_pct = (atr / last) * 100.0 if last > 0 else 999.0
        vol1m = vols[-1]

        # Trend alignment
        trend_ok = (ema21 > ema50 and last > ema21) if side == "BUY" else (ema21 < ema50 and last < ema21)

        # Short momentum (3m)
        mom = (last / closes[-4] - 1.0) * 100.0  # %
        mom_ok = (mom > 0.05) if side == "BUY" else (mom < -0.05)  # ±0.05%

        # Volume gate (optional)
        vol_ok = True if MIN_VOLUME <= 0 else (vol1m >= MIN_VOLUME)

        # ATR sanity
        atr_ok = (atr_pct <= MAX_ATR_PCT)

        # Score
        score = 0.0
        score += 4.0 if trend_ok else 0.0
        score += 3.0 if mom_ok else 0.0
        score += 2.0 if atr_ok else 0.0
        score += 1.0 if vol_ok else 0.0

        reasons = []
        if not trend_ok: reasons.append("trend_mismatch")
        if not mom_ok:   reasons.append("weak_momentum")
        if not atr_ok:   reasons.append("atr_too_high")
        if not vol_ok:   reasons.append("low_volume")

        return {"enter_ok": score >= MIN_QUALITY_SCORE, "score": round(score, 2), "reasons": reasons,
                "metrics": {"ema21": ema21, "ema50": ema50, "atr_pct": atr_pct, "mom_pct": mom, "vol1m": vol1m}}
    except Exception as e:
        log.warning("quality gate failed: %s", e)
        return {"enter_ok": False, "score": 0.0, "reasons": ["gate_error"]}

# ─────────── Ladders build ───────────
def _build_ladders(sym: str, side: str, qty: float,
                   tp_targets: Optional[List[float]], tp_splits: Optional[List[float]],
                   sl_targets: Optional[List[float]], sl_splits: Optional[List[float]]) -> Dict[str, Any]:
    plan = {"tp_orders": [], "sl_orders": []}

    def _prep(targets: Optional[List[float]], splits: Optional[List[float]], kind: str, limit_sign: int):
        if not targets: return
        L = len(targets)
        w = splits or []
        if not w or len(w) != L:
            w = [1.0 / L] * L
        tot = sum(max(0.0, float(x)) for x in w) or 1.0
        remain = qty
        for i, (t, wi) in enumerate(zip(targets, w), start=1):
            alloc = qty * (wi / tot) if i < L else remain
            _, qalloc = _q_qty(sym, max(0.0, alloc))
            if qalloc <= 0: continue
            remain = max(0.0, remain - qalloc)
            stop_str, stop_p = _q_price(sym, float(t))
            limit_p = _offset_bps(float(t), TP_LIMIT_OFFSET_BPS if kind=="TP" else SL_LIMIT_OFFSET_BPS, limit_sign)
            lim_str , lim_p  = _q_price(sym, limit_p)
            plan["tp_orders" if kind=="TP" else "sl_orders"].append({
                "stopPrice": stop_p, "price": lim_p, "qty": qalloc,
                "type": "TAKE_PROFIT" if kind=="TP" else "STOP"
            })

    if tp_targets: _prep(tp_targets, tp_splits, "TP", +1 if side=="BUY" else -1)
    if sl_targets: _prep(sl_targets, sl_splits, "SL", -1 if side=="BUY" else +1)
    return plan

# ─────────── Hybrid entry + escalation ───────────
async def _place_hybrid_entry(sym: str, side: str, qty: float, base_price: float, ref_entry: Optional[float]) -> Dict[str, Any]:
    """Places LIMIT (maker) + STOP (breakout). Cancels the other when one fills.
       If none fills and conditions justify → escalate to MARKET (if allowed)."""
    ref = ref_entry if ref_entry is not None else base_price
    if side == "BUY":
        limit_price = _offset_bps(ref, -ENTRY_BAND_BPS, +1)   # מתחת למחיר
        stop_price  = _offset_bps(ref, +STOP_BAND_BPS,  +1)   # מעל המחיר
    else:
        limit_price = _offset_bps(ref, +ENTRY_BAND_BPS, +1)   # מעל למחיר
        stop_price  = _offset_bps(ref, -STOP_BAND_BPS,  +1)   # מתחת למחיר

    limit_str, limit_p = _q_price(sym, limit_price)
    stop_str , stop_p  = _q_price(sym, stop_price)
    qty_str  , _       = _q_qty(sym, qty)

    # 1) LIMIT
    lim = futures_create_order(symbol=sym, side=side, type="LIMIT",
                               timeInForce="GTC", price=limit_str, quantity=qty_str)
    lim_id = str(lim.get("orderId") or "")

    # 2) STOP (STOP_LIMIT)
    stp = futures_create_order(symbol=sym, side=side, type="STOP",
                               timeInForce="GTC", stopPrice=stop_str, price=stop_str,
                               quantity=qty_str)
    stp_id = str(stp.get("orderId") or "")

    async def _is_filled(oid: str) -> bool:
        try:
            lst = get_all_orders(sym, limit=10) or []
            for o in lst:
                if str(o.get("orderId")) == str(oid):
                    st = (o.get("status") or "").upper()
                    if st in ("FILLED", "PARTIALLY_FILLED"):
                        return True
        except Exception:
            pass
        return False

    t0 = time.time()
    while True:
        lim_filled = await asyncio.to_thread(lambda: asyncio.run(_is_filled(lim_id)))
        stp_filled = await asyncio.to_thread(lambda: asyncio.run(_is_filled(stp_id)))

        if lim_filled and not stp_filled:
            try: futures_cancel_order(sym, stp_id)
            except Exception: pass
            return {"entry_kind": "LIMIT", "price": limit_p, "order": lim}

        if stp_filled and not lim_filled:
            try: futures_cancel_order(sym, lim_id)
            except Exception: pass
            return {"entry_kind": "STOP", "price": stop_p, "order": stp}

        # הסלמה — רק אם מוצדק
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
                return {"entry_kind": "MARKET_ESCALATE", "price": float(cur), "order": mkt}
            t0 = time.time()  # אם לא הסלמנו — נמשיך לנטר

        await asyncio.sleep(1.0)

# ─────────── Public API ───────────
async def execute_trade_live(
    symbol: str,
    side: str,
    *,
    budget: Optional[float] = None,
    leverage: int = 5,
    dry_run: bool = True,
    quantity: Optional[float] = None,
    entry: Optional[float] = None,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    tp_targets: Optional[List[float]] = None,
    tp_splits: Optional[List[float]] = None,
    sl_targets: Optional[List[float]] = None,
    sl_splits: Optional[List[float]] = None,
    confirm_first: bool = True,
    telegram_chat_id: Optional[int] = None,
) -> Dict[str, Any]:

    side = side.upper().strip()
    if side not in {"BUY","SELL"}:
        raise ValueError("side must be BUY/SELL")
    sym = symbol.upper().strip()

    base_price = get_price(sym) or futures_mark_price(sym)
    if not base_price or base_price <= 0:
        raise RuntimeError(f"Cannot fetch price for {sym}")

    qty = _calc_qty(sym, base_price, budget, leverage, quantity)

    # Gate (quality)
    gate = _quality_gate(sym, side)
    if not gate.get("enter_ok"):
        return {"ok": False, "reason": "quality_gate_rejected", "gate": gate}

    ladders = _build_ladders(sym, side, qty,
                             ([tp] if tp is not None else tp_targets), tp_splits,
                             ([sl] if sl is not None else sl_targets), sl_splits)

    plan: Dict[str, Any] = {
        "ok": True, "symbol": sym, "side": side, "qty": qty, "leverage": leverage,
        "base_price": base_price, "dry_run": dry_run,
        "entry_policy": f"HYBRID_LIMIT_STOP({ENTRY_BAND_BPS}/{STOP_BAND_BPS}bps)+MARKET_ESCALATION",
        "gate": gate, **ladders
    }

    if dry_run:
        plan["entry_simulation"] = {
            "limit_around": _offset_bps(entry or base_price, (-ENTRY_BAND_BPS if side=="BUY" else +ENTRY_BAND_BPS), +1),
            "stop_around":  _offset_bps(entry or base_price, (+STOP_BAND_BPS  if side=="BUY" else -STOP_BAND_BPS ), +1),
            "escalate_after_sec": ESCALATE_AFTER_S, "escalate_slip_bps": ESCALATE_SLIP_BPS,
            "allow_market_entry": ALLOW_MARKET_ENTRY,
        }
        return plan

    # אישור טלגרם אם נדרש
    if confirm_first:
        if not telegram_chat_id:
            return {"ok": False, "reason": "telegram_chat_id_required"}
        approval = await require_approval(telegram_chat_id, {
            "symbol": sym, "side": side, "qty": qty, "leverage": leverage
        })
        if approval.get("status") != "approved":
            return {"ok": False, "status": approval.get("status"), "reason": "not_approved"}

    # ביצוע
    try:
        set_leverage(sym, int(leverage))
    except Exception as e:
        log.warning("set_leverage failed: %s", e)

    entry_res = await _place_hybrid_entry(sym, side, qty, base_price, entry)
    plan["entry_result"] = entry_res

    # יציאות — reduceOnly GTC
    close_side = "SELL" if side=="BUY" else "BUY"
    for arr, otype in ((plan["tp_orders"], "TAKE_PROFIT"), (plan["sl_orders"], "STOP")):
        for o in arr:
            try:
                resp = futures_create_order(
                    symbol=sym, side=close_side, type=otype,
                    timeInForce="GTC", reduceOnly=True,
                    stopPrice=_q_price(sym, float(o["stopPrice"]))[0],
                    price=_q_price(sym, float(o["price"]))[0],
                    quantity=_q_qty(sym, float(o["qty"]))[0],
                )
                o["response"] = resp
            except Exception as e:
                o["response"] = {"ok": False, "error": str(e)}

    return plan


































































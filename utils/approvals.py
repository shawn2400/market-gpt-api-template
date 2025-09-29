# utils/approvals.py
from __future__ import annotations

import os, time, hashlib, json, asyncio, logging
from typing import Dict, Any, List, Optional, Tuple, Callable, Awaitable

log = logging.getLogger("algogpt.approvals")

# -------- helpers ----------
def _as_bool(s: Optional[str], default: bool = False) -> bool:
    return str(s).strip().lower() in {"1","true","yes","on"} if s is not None else default
def _as_float(s: Optional[str], default: float) -> float:
    try: return float(str(s).strip())
    except Exception: return default
def _as_int(s: Optional[str], default: int) -> int:
    try: return int(str(s).strip())
    except Exception: return default

# -------- env / policy ----------
APPROVAL_ENABLED = _as_bool(os.getenv("APPROVAL_ENABLED","1"), True)
APPROVAL_SUCCESS_MIN = _as_float(os.getenv("APPROVAL_SUCCESS_MIN","60"), 60.0)
APPROVAL_RR_MIN = _as_float(os.getenv("APPROVAL_RR_MIN","1.30"), 1.30)
MIN_TP_SL_DIFF_PCT = _as_float(os.getenv("MIN_TP_SL_DIFF_PCT","3.0"), 3.0)
APPROVAL_MAX_SL_PCT = _as_float(os.getenv("APPROVAL_MAX_SL_PCT","3.0"), 3.0)
MIN_NOTIONAL_USDT = _as_float(os.getenv("MIN_NOTIONAL_USDT","5"), 5.0)
APPROVAL_REQUIRE_FRESH_PRICE = _as_bool(os.getenv("APPROVAL_REQUIRE_FRESH_PRICE","1"), True)
PRICE_MAX_AGE_SEC = _as_int(os.getenv("PRICE_MAX_AGE_SEC","15"), 15)
WATCHLIST_CSV = os.getenv("WATCHLIST","") or os.getenv("HEALTH_SYMBOLS","")
REQUIRE_IN_WATCHLIST = _as_bool(os.getenv("APPROVAL_REQUIRE_WATCHLIST","1"), True)
APPROVAL_DUP_COOLDOWN_SEC = _as_int(os.getenv("APPROVAL_DUP_COOLDOWN_SEC","300"), 300)
MAX_LEVERAGE = _as_int(os.getenv("MAX_LEVERAGE","35"), 35)

TICKET_TTL_SEC = _as_int(os.getenv("CONFIRM_TTL_SEC","180"), 180)
AUTO_DECIDE_EXPIRED = _as_bool(os.getenv("APPROVAL_AUTO_REJECT_EXPIRED","1"), True)

# -------- recent map for preflight dup ----------
_recent: Dict[str, float] = {}

def _purge_recent(now: float) -> None:
    cut = now - max(60, APPROVAL_DUP_COOLDOWN_SEC)
    for k, ts in list(_recent.items()):
        if ts < cut: _recent.pop(k, None)

def _key_for(tp: Dict[str, Any]) -> str:
    base = {
        "symbol": str(tp.get("symbol","")).upper(),
        "side": str(tp.get("side","")).upper(),
        "entry": round(float(tp.get("entry", tp.get("price",0.0)) or 0.0), 8),
        "sl":    round(float(tp.get("sl", tp.get("sl_price",0.0)) or 0.0), 8),
        "tp1":   round(float(tp.get("tp1",0.0) or 0.0), 8),
        "lev":   int(tp.get("leverage") or tp.get("lev") or 0),
        "interval": str(tp.get("interval","") or ""),
    }
    raw = json.dumps(base, sort_keys=True, separators=(",",":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]

def _rr(entry: float, sl: float, tp1: float, side: str) -> Optional[float]:
    try:
        e = float(entry); s = float(sl); t = float(tp1); sd = (side or "").upper()
        risk = abs(e - s)
        if risk <= 0: return None
        reward = (t - e) if sd in ("BUY","LONG") else (e - t)
        return float(reward / risk) if reward > 0 else None
    except Exception:
        return None

def _pct(a: float, b: float) -> float:
    try: return abs((a - b) / b) * 100.0
    except Exception: return 0.0

def _in_watchlist(sym: str) -> bool:
    if not REQUIRE_IN_WATCHLIST: return True
    wl = [x.strip().upper() for x in (WATCHLIST_CSV or "").split(",") if x.strip()]
    return (not wl) or (sym.upper() in wl)

def _fresh_price_ok(symbol: str) -> Tuple[bool, Optional[float]]:
    if not APPROVAL_REQUIRE_FRESH_PRICE: return (True, None)
    try:
        from utils.ws_fallback import is_price_fresh, get_price  # type: ignore
        ok = is_price_fresh(symbol, max_age_sec=PRICE_MAX_AGE_SEC)
        px = float(get_price(symbol) or 0.0)
        return (bool(ok), px if px > 0 else None)
    except Exception:
        try:
            from utils.binance_client import get_price as http_price  # type: ignore
            px = float(http_price(symbol) or 0.0)
            return (px > 0, px if px > 0 else None)
        except Exception:
            return (False, None)

def _aligned(val: float, step: float, tol: float = 1e-10) -> bool:
    if step <= 0: return True
    k = round(val / step); return abs(k * step - val) <= max(tol, step * 1e-8)

def _precision_checks(symbol: str, entry: float, sl: float, tp1: float) -> List[str]:
    out: List[str] = []
    try:
        from utils.binance_client import get_symbol_info
        info = get_symbol_info(symbol)
        if not info: return out
        tick = None
        for f in info.get("filters", []):
            if f.get("filterType") == "PRICE_FILTER":
                tick = float(f.get("tickSize","0")) or None
        if tick:
            for name, val in [("entry", entry), ("sl", sl), ("tp1", tp1)]:
                if not _aligned(float(val), float(tick)):
                    out.append(f"{name}_not_aligned_tick({val})")
    except Exception:
        pass
    return out

def preflight_proposal(tp: Dict[str, Any], *, mutate_state: bool = True) -> Dict[str, Any]:
    out_errors: List[str] = []; out_warns: List[str] = []; metrics: Dict[str, Any] = {}
    if not APPROVAL_ENABLED:
        return {"ok": True, "errors": [], "warnings": [], "metrics": {"disabled": True}}

    symbol = str(tp.get("symbol","")).upper()
    side = str(tp.get("side","")).upper()
    entry = float(tp.get("entry", tp.get("price", 0.0)) or 0.0)
    sl    = float(tp.get("sl", tp.get("sl_price", 0.0)) or 0.0)
    tp1   = float(tp.get("tp1", 0.0) or 0.0)

    if not symbol: out_errors.append("missing_symbol")
    if side not in ("BUY","SELL","LONG","SHORT"): out_errors.append("bad_side")
    if entry <= 0: out_errors.append("bad_entry")
    if sl    <= 0: out_errors.append("bad_sl")
    if tp1   <= 0: out_errors.append("bad_tp1")
    if out_errors: return {"ok": False, "errors": out_errors, "warnings": out_warns, "metrics": metrics}

    if not _in_watchlist(symbol): out_errors.append("symbol_not_in_watchlist")

    fp_ok, px = _fresh_price_ok(symbol)
    metrics["fresh_price_ok"] = fp_ok; metrics["last_price"] = px
    if not fp_ok: out_warns.append("stale_or_missing_price")

    min_pct = float(MIN_TP_SL_DIFF_PCT)
    if _pct(entry, sl)  < min_pct: out_errors.append(f"entry_sl_too_close(<{min_pct:.3f}%)")
    if _pct(entry, tp1) < min_pct: out_errors.append(f"entry_tp1_too_close(<{min_pct:.3f}%)")
    if _pct(entry, sl)  > float(APPROVAL_MAX_SL_PCT): out_errors.append(f"sl_too_far(>{APPROVAL_MAX_SL_PCT:.2f}%)")

    rr = _rr(entry, sl, tp1, side); metrics["rr"] = rr
    if rr is None or rr < APPROVAL_RR_MIN:
        out_errors.append(f"rr_below_min({rr:.2f}<{APPROVAL_RR_MIN:.2f})" if rr is not None else "rr_invalid")

    sp = tp.get("success_pct")
    if sp is not None:
        try:
            spf = float(sp); metrics["success_pct"] = spf
            if spf < APPROVAL_SUCCESS_MIN:
                out_errors.append(f"success_pct_below_min({spf:.1f}<{APPROVAL_SUCCESS_MIN:.1f})")
        except Exception:
            out_warns.append("success_pct_not_numeric")

    lev = int(tp.get("leverage") or tp.get("lev") or 0)
    if lev <= 0: out_warns.append("missing_leverage")
    elif lev > MAX_LEVERAGE: out_errors.append(f"leverage_above_cap(x{lev}>x{MAX_LEVERAGE})")
    metrics["leverage"] = lev

    budget = tp.get("budget") or tp.get("budget_usd")
    if budget is not None and lev > 0:
        try:
            notional = float(budget) * float(lev); metrics["notional_est"] = notional
            if notional < MIN_NOTIONAL_USDT:
                out_errors.append(f"notional_below_min(${notional:.2f} < ${MIN_NOTIONAL_USDT:.2f})")
        except Exception:
            out_warns.append("notional_est_failed")

    out_errors.extend(_precision_checks(symbol, entry, sl, tp1))

    now = time.time(); key = _key_for(tp); last = _recent.get(key)
    if last and (now - last < APPROVAL_DUP_COOLDOWN_SEC): out_errors.append("duplicate_recent")
    if mutate_state:
        _purge_recent(now)
        if not last or (now - last >= APPROVAL_DUP_COOLDOWN_SEC): _recent[key] = now

    ok = (len(out_errors) == 0)
    return {"ok": ok, "errors": out_errors, "warnings": out_warns, "metrics": metrics}

def can_auto_forward(tp: Dict[str, Any]) -> bool:
    res = preflight_proposal(tp, mutate_state=False)
    return bool(res.get("ok", False))

# ========================= ConfirmStore =========================
# שומר כרטיסי אישור + handler לביצוע בפועל
Handler = Callable[[], Awaitable[Dict[str, Any]]]

class ConfirmStore:
    _P: Dict[str, Dict[str, Any]] = {}         # idem -> record
    _RUN: Dict[str, Handler] = {}              # idem -> async handler
    _L = asyncio.Lock()

    @classmethod
    def pending(cls) -> List[Dict[str, Any]]:
        return [dict(v) for v in cls._P.values() if v.get("status") == "pending"]

    @classmethod
    def create(cls, payload: Dict[str, Any], handler: Optional[Handler] = None) -> str:
        """
        payload MUST include: symbol, side, leverage/budget/qty (לוגית), ttl_sec (optional)
        returns idem (ticket id)
        """
        idem = str(payload.get("ticket_id") or payload.get("idem") or f"{int(time.time()*1000)}_{hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]}")
        rec = dict(payload)
        rec["idem"] = idem
        rec["ticket_id"] = idem
        rec["status"] = "pending"
        rec["created_ts"] = int(time.time())
        rec["ttl_sec"] = int(payload.get("ttl_sec") or TICKET_TTL_SEC)
        cls._P[idem] = rec
        if handler:
            cls._RUN[idem] = handler
        return idem

    @classmethod
    def get(cls, idem: str) -> Optional[Dict[str, Any]]:
        return dict(cls._P.get(idem) or {}) if idem in cls._P else None

    @classmethod
    def approve(cls, idem: str, approver: Optional[str] = None) -> Dict[str, Any]:
        it = cls._P.get(idem)
        if not it:
            return {"ok": False, "error": "not_found"}
        if it.get("status") != "pending":
            return {"ok": False, "error": "not_pending"}
        it["status"] = "approved"
        it["approved_ts"] = int(time.time())
        if approver: it["approved_by"] = str(approver)
        return {"ok": True, "idem": idem}

    @classmethod
    def reject(cls, idem: str, approver: Optional[str] = None) -> Dict[str, Any]:
        it = cls._P.get(idem)
        if not it:
            return {"ok": False, "error": "not_found"}
        if it.get("status") != "pending":
            return {"ok": False, "error": "not_pending"}
        it["status"] = "rejected"
        it["rejected_ts"] = int(time.time())
        if approver: it["rejected_by"] = str(approver)
        # אין צורך לשמור handler לאחר דחייה
        cls._RUN.pop(idem, None)
        return {"ok": True, "idem": idem}

    @classmethod
    async def run(cls, idem: str) -> Dict[str, Any]:
        """
        מריץ את ה-handler אם הסטטוס 'approved'. מחזיר תוצאה/שגיאה.
        """
        it = cls._P.get(idem)
        if not it:
            return {"ok": False, "error": "not_found"}
        if it.get("status") != "approved":
            return {"ok": False, "error": "not_approved"}
        h = cls._RUN.pop(idem, None)
        if not h:
            return {"ok": False, "error": "trade executor missing"}
        try:
            async with cls._L:
                res = await h()
        except Exception as e:
            log.exception("ConfirmStore.run failed")
            return {"ok": False, "error": str(e)}
        it["status"] = "executed"
        it["executed_ts"] = int(time.time())
        it["result"] = res
        return {"ok": True, "result": res}

    @classmethod
    def decide(cls, ticket_id: str, approved: bool) -> Dict[str, Any]:
        return cls.approve(ticket_id) if approved else cls.reject(ticket_id)

    @classmethod
    def flush_all(cls) -> None:
        cls._P.clear(); cls._RUN.clear()

    # aliases
    flush = reset = flush_all

# ========================= Notifier bridge =========================
async def send_confirm_request(ticket_id: str, plan: Dict[str, Any]) -> None:
    """
    Back-compat shim: שולח הודעת אישור לטלגרם.
    """
    try:
        from utils.telegram_notifier import send_trade_approval  # type: ignore
        await send_trade_approval(ticket_id, plan)
    except Exception:
        pass

# ========================= Approval orchestrator =========================
async def require_approval(chat_id: int, plan: Dict[str, Any], handler: Optional[Handler] = None) -> Dict[str, Any]:
    """
    יוצר כרטיס אישור ומחזיר:
      - {"status":"approved"} אם auto-approve מופעל ומותר
      - {"status":"pending","idem":...,"ttl_sec":...} אם מחכה לאישור ידני
      - {"status":"rejected", ...} אם נדחה אוטומטית/פג תוקף
    אם handler סופק — יירשם, והרצה תתבצע ע"י ConfirmStore.run(idem) לאחר אישור.
    """
    ttl = int(plan.get("ttl_sec") or TICKET_TTL_SEC)
    idem = ConfirmStore.create({**plan, "ttl_sec": ttl, "ticket_id": plan.get("idem") or None}, handler=handler)

    # attach idem to plan for links
    plan = dict(plan); plan["idem"] = idem; plan["ttl_sec"] = ttl

    # auto-approve policy
    auto = False
    try:
        from utils.telegram_notifier_core import should_auto_approve_trade  # type: ignore
        auto = bool(should_auto_approve_trade(plan))
    except Exception:
        auto = False

    if auto:
        ConfirmStore.approve(idem, approver="auto")
        return {"status": "approved", "idem": idem, "ttl_sec": ttl}

    # send telegram approval with inline keyboard
    try:
        from utils.telegram_notifier import send_trade_approval  # type: ignore
        await send_trade_approval(idem, plan, chat_id=chat_id if chat_id else None)
    except Exception as e:
        log.warning("send_trade_approval failed: %s", e)

    return {"status": "pending", "idem": idem, "ttl_sec": ttl}











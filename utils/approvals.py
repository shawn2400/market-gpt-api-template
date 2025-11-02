
# utils/approvals.py
from __future__ import annotations

import os, time, hashlib, json, asyncio, logging
from typing import Dict, Any, List, Optional, Tuple, Callable, Awaitable

log = logging.getLogger("algogpt.approvals")

# -------- פונקציות עזר בסיסיות ----------
def _as_bool(s: Optional[str], default: bool = False) -> bool:
    # המרה בטוחה של מחרוזת לערך בוליאני (תומך ב־1/true/yes/on)
    return str(s).strip().lower() in {"1","true","yes","on"} if s is not None else default

def _as_float(s: Optional[str], default: float) -> float:
    # המרה בטוחה ל־float עם ערך ברירת־מחדל במקרה של שגיאה
    try:
        return float(str(s).strip())
    except Exception:
        return default

def _as_int(s: Optional[str], default: int) -> int:
    # המרה בטוחה ל־int עם ערך ברירת־מחדל במקרה של שגיאה
    try:
        return int(str(s).strip())
    except Exception:
        return default

# -------- קונפיגורציית סביבה / מדיניות אישור ----------
APPROVAL_ENABLED = _as_bool(os.getenv("APPROVAL_ENABLED","1"), True)                       # האם מנגנון האישור פעיל
APPROVAL_SUCCESS_MIN = _as_float(os.getenv("APPROVAL_SUCCESS_MIN","60"), 60.0)            # סף מינימלי לאומדן הסתברות הצלחה (%)
APPROVAL_RR_MIN = _as_float(os.getenv("APPROVAL_RR_MIN","1.30"), 1.30)                    # יחס סיכון/סיכוי מינימלי (RR)
MIN_TP_SL_DIFF_PCT = _as_float(os.getenv("MIN_TP_SL_DIFF_PCT","3.0"), 3.0)                # מרחק מינימלי באחוזים בין Entry ל־TP/SL
APPROVAL_MAX_SL_PCT = _as_float(os.getenv("APPROVAL_MAX_SL_PCT","3.0"), 3.0)              # מרחק מקסימלי מותר ל־SL מה־Entry (%)
MIN_NOTIONAL_USDT = _as_float(os.getenv("MIN_NOTIONAL_USDT","5"), 5.0)                    # נומינלי מינימלי מוערך (תקציב×מינוף)
APPROVAL_REQUIRE_FRESH_PRICE = _as_bool(os.getenv("APPROVAL_REQUIRE_FRESH_PRICE","1"), True)  # האם נדרש מחיר "טרי"
PRICE_MAX_AGE_SEC = _as_int(os.getenv("PRICE_MAX_AGE_SEC","15"), 15)                      # גיל מקסימלי לשער אחרון (שניות)
WATCHLIST_CSV = os.getenv("WATCHLIST","") or os.getenv("HEALTH_SYMBOLS","")               # רשימת סימבולים מאושרת (CSV)
REQUIRE_IN_WATCHLIST = _as_bool(os.getenv("APPROVAL_REQUIRE_WATCHLIST","1"), True)        # האם חייב להיות ברשימת המעקב
APPROVAL_DUP_COOLDOWN_SEC = _as_int(os.getenv("APPROVAL_DUP_COOLDOWN_SEC","300"), 300)    # חלון קירור למניעת כפילויות (שניות)
MAX_LEVERAGE = _as_int(os.getenv("MAX_LEVERAGE","35"), 35)                                # מינוף מקסימלי מותר

TICKET_TTL_SEC = _as_int(os.getenv("CONFIRM_TTL_SEC","180"), 180)                         # TTL לכרטיס אישור (שניות)
AUTO_DECIDE_EXPIRED = _as_bool(os.getenv("APPROVAL_AUTO_REJECT_EXPIRED","1"), True)       # האם לדחות אוטומטית כשפג תוקף

# -------- אחסון "אחרונים" למניעת כפילויות בפרה־פלייט ----------
APPROVAL_RECENT_BACKEND = (os.getenv("APPROVAL_RECENT_BACKEND","memory").strip().lower()) # backend: memory/redis
RECENT_KEY_PREFIX = os.getenv("APPROVAL_RECENT_KEY_PREFIX","approvals:recent:")

_recent: Dict[str, float] = {}
_r = None
if APPROVAL_RECENT_BACKEND == "redis":
    try:
        import redis  # type: ignore
        _r = redis.Redis.from_url(os.getenv("REDIS_URL",""), decode_responses=True)
    except Exception as e:
        log.warning("Redis לא זמין לשכבת recent של approvals: %s — מעבר ל־memory", e)
        _r = None

def _recent_get(k: str) -> float:
    # קריאה מאחסון recent (Redis אם זמין, אחרת זיכרון)
    if _r:
        try:
            ts = _r.get(f"{RECENT_KEY_PREFIX}{k}")
            return float(ts or 0.0)
        except Exception:
            return 0.0
    return _recent.get(k, 0.0)

def _recent_set(k: str, ts: float, ttl: int) -> None:
    # כתיבה לאחסון recent עם TTL (ב־Redis) או בזיכרון
    if _r:
        try:
            _r.setex(f"{RECENT_KEY_PREFIX}{k}", ttl, str(ts))
            return
        except Exception:
            pass
    _recent[k] = ts

def _purge_recent(now: float) -> None:
    # ניקוי רשומות ישנות במצב memory (ב־Redis TTL מטפל בכך)
    if _r:
        return  # Redis מנקה לפי TTL
    cut = now - max(60, APPROVAL_DUP_COOLDOWN_SEC)
    for k, ts in list(_recent.items()):
        if ts < cut:
            _recent.pop(k, None)

def _key_for(tp: Dict[str, Any]) -> str:
    # בניית מפתח־אצבע (hash) לזיהוי כפילויות על בסיס שדות מהותיים
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
    # חישוב יחס סיכון/סיכוי (RR) בהתאם לכיוון (BUY/LONG מול SELL/SHORT)
    try:
        e = float(entry); s = float(sl); t = float(tp1); sd = (side or "").upper()
        risk = abs(e - s)
        if risk <= 0:
            return None
        reward = (t - e) if sd in ("BUY","LONG") else (e - t)
        return float(reward / risk) if reward > 0 else None
    except Exception:
        return None

def _pct(a: float, b: float, ref: Optional[float] = None) -> float:
    # חישוב מרחק יחסי באחוזים בין שני ערכים סביב ref (כברירת־מחדל a)
    try:
        r = float(a if ref is None else ref)
        if r == 0:
            return 0.0
        return abs((float(a) - float(b)) / r) * 100.0
    except Exception:
        return 0.0

def _in_watchlist(sym: str) -> bool:
    # בדיקה האם הסימבול מאושר ברשימת המעקב (אם דרוש)
    if not REQUIRE_IN_WATCHLIST:
        return True
    wl = [x.strip().upper() for x in (WATCHLIST_CSV or "").split(",") if x.strip()]
    return (not wl) or (sym.upper() in wl)

def _fresh_price_ok(symbol: str) -> Tuple[bool, Optional[float]]:
    # בדיקת זמינות מחיר "טרי" והחזרתו (אם קיים)
    if not APPROVAL_REQUIRE_FRESH_PRICE:
        return (True, None)
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
    # בדיקה אם ערך מיושר ל־tickSize בהתאם לטולרנס קטן
    if step <= 0:
        return True
    k = round(val / step)
    return abs(k * step - val) <= max(tol, step * 1e-8)

def _precision_checks(symbol: str, entry: float, sl: float, tp1: float) -> List[str]:
    # וולידציית דיוק מחירים מול tickSize של הסימבול; מחזיר רשימת שגיאות אם לא מיושר
    out: List[str] = []
    tick: Optional[float] = None
    try:
        from utils.binance_client import get_symbol_info  # type: ignore
        info = get_symbol_info(symbol)
        if info and "filters" in info:
            for f in info.get("filters", []):
                if f.get("filterType") == "PRICE_FILTER":
                    tick = float(f.get("tickSize","0") or 0.0) or None
                    break
    except Exception:
        pass
    if tick is None:
        try:
            from utils.binance_client import get_symbol_filters  # type: ignore
            flt = get_symbol_filters(symbol) or {}
            ts = flt.get("tickSize")
            tick = float(ts) if ts is not None else None
        except Exception:
            tick = None
    if tick:
        for name, val in (("entry", entry), ("sl", sl), ("tp1", tp1)):
            try:
                if not _aligned(float(val), float(tick)):
                    out.append(f"{name}_not_aligned_tick({val})")
            except Exception:
                continue
    return out

def preflight_proposal(tp: Dict[str, Any], *, mutate_state: bool = True) -> Dict[str, Any]:
    """
    בדיקות פרה־פלייט לתכנית טרייד:
    • ולידציה של שדות חובה (symbol/side/entry/sl/tp1)
    • בדיקות מדיניות: Watchlist, מחיר עדכני, מרחקי SL/TP, RR מינימלי, מינוף ונומינלי
    • בדיקות דיוק מול tickSize
    • חסם כפילויות (חלון קירור) עם אפשרות לעדכן מצב (mutate_state)
    """
    out_errors: List[str] = []
    out_warns: List[str] = []
    metrics: Dict[str, Any] = {}

    if not APPROVAL_ENABLED:
        return {"ok": True, "errors": [], "warnings": [], "metrics": {"disabled": True}}

    symbol = str(tp.get("symbol","")).upper()
    side = str(tp.get("side","")).upper()
    entry = float(tp.get("entry", tp.get("price", 0.0)) or 0.0)
    sl    = float(tp.get("sl", tp.get("sl_price", 0.0)) or 0.0)
    tp1   = float(tp.get("tp1", 0.0) or 0.0)

    # שדות חובה
    if not symbol:
        out_errors.append("missing_symbol")
    if side not in ("BUY","SELL","LONG","SHORT"):
        out_errors.append("bad_side")
    if entry <= 0:
        out_errors.append("bad_entry")
    if sl <= 0:
        out_errors.append("bad_sl")
    if tp1 <= 0:
        out_errors.append("bad_tp1")
    if out_errors:
        return {"ok": False, "errors": out_errors, "warnings": out_warns, "metrics": metrics}

    # Watchlist (אם נדרש)
    if not _in_watchlist(symbol):
        out_errors.append("symbol_not_in_watchlist")

    # מחיר עדכני (טריות)
    fp_ok, px = _fresh_price_ok(symbol)
    metrics["fresh_price_ok"] = fp_ok
    metrics["last_price"] = px
    if not fp_ok:
        out_warns.append("stale_or_missing_price")

    # מרחקים מינימליים/מקסימליים בין Entry ל־SL/TP
    min_pct = float(MIN_TP_SL_DIFF_PCT)
    if _pct(entry, sl, ref=entry)  < min_pct:
        out_errors.append(f"entry_sl_too_close(<{min_pct:.3f}%)")
    if _pct(entry, tp1, ref=entry) < min_pct:
        out_errors.append(f"entry_tp1_too_close(<{min_pct:.3f}%)")
    if _pct(entry, sl, ref=entry)  > float(APPROVAL_MAX_SL_PCT):
        out_errors.append(f"sl_too_far(>{APPROVAL_MAX_SL_PCT:.2f}%)")

    # RR מינימלי
    rr = _rr(entry, sl, tp1, side); metrics["rr"] = rr
    if rr is None or rr < APPROVAL_RR_MIN:
        out_errors.append(f"rr_below_min({rr:.2f}<{APPROVAL_RR_MIN:.2f})" if rr is not None else "rr_invalid")

    # אומדן הצלחה (אופציונלי)
    sp = tp.get("success_pct")
    if sp is not None:
        try:
            spf = float(sp); metrics["success_pct"] = spf
            if spf < APPROVAL_SUCCESS_MIN:
                out_errors.append(f"success_pct_below_min({spf:.1f}<{APPROVAL_SUCCESS_MIN:.1f})")
        except Exception:
            out_warns.append("success_pct_not_numeric")

    # מינוף ומגבלות
    lev = int(tp.get("leverage") or tp.get("lev") or 0)
    if lev <= 0:
        out_warns.append("missing_leverage")
    elif lev > MAX_LEVERAGE:
        out_errors.append(f"leverage_above_cap(x{lev}>x{MAX_LEVERAGE})")
    metrics["leverage"] = lev

    # נומינלי משוער (תקציב×מינוף) אם קיים תקציב
    budget = tp.get("budget") or tp.get("budget_usd")
    if budget is not None and lev > 0:
        try:
            notional = float(budget) * float(lev); metrics["notional_est"] = notional
            if notional < MIN_NOTIONAL_USDT:
                out_errors.append(f"notional_below_min(${notional:.2f} < ${MIN_NOTIONAL_USDT:.2f})")
        except Exception:
            out_warns.append("notional_est_failed")

    # בדיקות דיוק מול tickSize
    out_errors.extend(_precision_checks(symbol, entry, sl, tp1))

    # חסם כפילויות בחלון קירור
    now = time.time()
    key = _key_for(tp)
    last = _recent_get(key)
    if last and (now - last < APPROVAL_DUP_COOLDOWN_SEC):
        out_errors.append("duplicate_recent")
    if mutate_state:
        _purge_recent(now)
        if not last or (now - last >= APPROVAL_DUP_COOLDOWN_SEC):
            _recent_set(key, now, APPROVAL_DUP_COOLDOWN_SEC)

    ok = (len(out_errors) == 0)
    return {"ok": ok, "errors": out_errors, "warnings": out_warns, "metrics": metrics}

def can_auto_forward(tp: Dict[str, Any]) -> bool:
    # בדיקה מהירה האם ניתן לעבור לאישור אוטומטי (ללא עדכון־מצב)
    res = preflight_proposal(tp, mutate_state=False)
    return bool(res.get("ok", False))

# ========================= ConfirmStore — מחסן אישורים בזיכרון =========================
from typing import Callable, Awaitable
Handler = Callable[[], Awaitable[Dict[str, Any]]]

class ConfirmStore:
    _P: Dict[str, Dict[str, Any]] = {}      # מיפוי idem -> רשומת כרטיס
    _RUN: Dict[str, Handler] = {}            # מיפוי idem -> Handler אסינכרוני להפעלה
    _L = asyncio.Lock()                      # נעילה לריצות מתוזמנות

    @classmethod
    def pending(cls) -> List[Dict[str, Any]]:
        # החזרת כל הכרטיסים בסטטוס "pending"
        return [dict(v) for v in cls._P.values() if v.get("status") == "pending"]

    @classmethod
    def create(cls, payload: Dict[str, Any], handler: Optional[Handler] = None) -> str:
        # יצירת כרטיס חדש עם idem יציב (מה־payload אם קיים או hash)
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
        # שליפת כרטיס לפי idem
        # Direct lookup
        if idem in cls._P:
            return dict(cls._P.get(idem))
        
        # Fallback: try pattern matching for shortened IDs
        # This handles cases where we're looking for a shortened ID but stored the full ID
        for key in cls._P.keys():
            # Check if the provided ID is a shortened version of the stored key
            if idem in key or key in idem:
                log.debug(f"[ConfirmStore] Found match via pattern: {idem} -> {key}")
                return dict(cls._P.get(key))
            
            # Check for GRID format variations (g prefix)
            if idem.startswith('TKT-') and key.startswith('g'):
                if idem[4:] in key or key in idem:
                    log.debug(f"[ConfirmStore] Found GRID match: {idem} -> {key}")
                    return dict(cls._P.get(key))
            elif key.startswith('TKT-') and idem.startswith('g'):
                if key[4:] in idem or idem in key:
                    log.debug(f"[ConfirmStore] Found GRID match: {idem} -> {key}")
                    return dict(cls._P.get(key))
        
        return None

    @classmethod
    def approve(cls, idem: str, approver: Optional[str] = None) -> Dict[str, Any]:
        # שינוי סטטוס ל־approved, רישום מאשר ושעת אישור
        it = cls._P.get(idem)
        if not it:
            return {"ok": False, "error": "not_found"}
        if it.get("status") != "pending":
            return {"ok": False, "error": "not_pending"}
        it["status"] = "approved"
        it["approved_ts"] = int(time.time())
        if approver:
            it["approved_by"] = str(approver)
        return {"ok": True, "idem": idem}

    @classmethod
    def reject(cls, idem: str, approver: Optional[str] = None) -> Dict[str, Any]:
        # שינוי סטטוס ל־rejected, הסרת ה־handler (אם הוגדר)
        it = cls._P.get(idem)
        if not it:
            return {"ok": False, "error": "not_found"}
        if it.get("status") != "pending":
            return {"ok": False, "error": "not_pending"}
        it["status"] = "rejected"
        it["rejected_ts"] = int(time.time())
        if approver:
            it["rejected_by"] = str(approver)
        cls._RUN.pop(idem, None)
        return {"ok": True, "idem": idem}

    @classmethod
    async def run(cls, idem: str) -> Dict[str, Any]:
        # הפעלת ה־handler של כרטיס שאושר; עדכון סטטוס ל־executed ושמירת תוצאה
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
            log.exception("ConfirmStore.run נכשל")
            return {"ok": False, "error": str(e)}
        it["status"] = "executed"
        it["executed_ts"] = int(time.time())
        it["result"] = res
        return {"ok": True, "result": res}

    @classmethod
    def decide(cls, ticket_id: str, approved: bool) -> Dict[str, Any]:
        # סיוע: decide -> approve/reject לפי הדגל
        return cls.approve(ticket_id) if approved else cls.reject(ticket_id)

    @classmethod
    def flush_all(cls) -> None:
        # ניקוי מלא של כל הכרטיסים וה־handlers
        cls._P.clear()
        cls._RUN.clear()

    flush = reset = flush_all  # שמות חלופיים לניקוי

# ========================= גשר התראות (Notifier) =========================
async def send_confirm_request(ticket_id: str, plan: Dict[str, Any]) -> None:
    # שליחת בקשת אישור לטלגרם (אם המודול זמין); שקט בשגיאה
    try:
        from utils.telegram_notifier import send_trade_approval  # type: ignore
        await send_trade_approval(ticket_id, plan)
    except Exception:
        pass

# ========================= אורקסטרטור האישור =========================
async def require_approval(chat_id: int, plan: Dict[str, Any], handler: Optional[Handler] = None) -> Dict[str, Any]:
    """
    יוצר כרטיס אישור, בוחר אוטומטית לאשר אם המדיניות מאפשרת (auto-approve),
    אחרת שולח בקשת אישור לטלגרם ומחזיר סטטוס התחלתי (pending/approved).
    """
    ttl = int(plan.get("ttl_sec") or TICKET_TTL_SEC)
    idem = ConfirmStore.create({**plan, "ttl_sec": ttl, "ticket_id": plan.get("idem") or None}, handler=handler)

    plan = dict(plan)
    plan["idem"] = idem
    plan["ttl_sec"] = ttl

    auto = False
    try:
        from utils.telegram_notifier_core import should_auto_approve_trade  # type: ignore
        auto = bool(should_auto_approve_trade(plan))
    except Exception:
        auto = False

    if auto:
        ConfirmStore.approve(idem, approver="auto")
        return {"status": "approved", "idem": idem, "ttl_sec": ttl}

    try:
        from utils.telegram_notifier import send_trade_approval  # type: ignore
        await send_trade_approval(idem, plan, chat_id=chat_id if chat_id else None)
    except Exception as e:
        log.warning("send_trade_approval נכשל: %s", e)

    return {"status": "pending", "idem": idem, "ttl_sec": ttl}


__all__ = [
    "APPROVAL_ENABLED","APPROVAL_SUCCESS_MIN","APPROVAL_RR_MIN","MIN_TP_SL_DIFF_PCT",
    "APPROVAL_MAX_SL_PCT","MIN_NOTIONAL_USDT","APPROVAL_REQUIRE_FRESH_PRICE","PRICE_MAX_AGE_SEC",
    "WATCHLIST_CSV","REQUIRE_IN_WATCHLIST","APPROVAL_DUP_COOLDOWN_SEC","MAX_LEVERAGE",
    "TICKET_TTL_SEC","AUTO_DECIDE_EXPIRED",
    "preflight_proposal","can_auto_forward","ConfirmStore",
    "send_confirm_request","require_approval",
]













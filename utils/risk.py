# utils/risk.py
from __future__ import annotations
import logging, os, time, threading
from typing import Optional, Dict, Any

log = logging.getLogger("algogpt.risk")

# ===== Optional deps (fallbacks if missing) =====
try:
    from utils.budget import get_trade_budget_usdt  # dynamic budget policy (env-driven)
except Exception:
    def get_trade_budget_usdt(*, symbol: str, quality: Optional[float] = None,
                              atr: Optional[float] = None, price: Optional[float] = None) -> float:
        """
        Fallback budget rule: ENV or default 25 USDT.
        """
        try:
            return float(os.getenv("DEFAULT_TRADE_BUDGET_USDT", "25"))
        except Exception:
            return 25.0

try:
    from utils.calculate_quantity import calculate_quantity  # respects exchange filters
except Exception:
    def calculate_quantity(*, symbol: str, entry_price: float, leverage: float, budget_usdt: float) -> float:
        """
        Fallback qty rule: naive division (no filters). Meant only to avoid import crash.
        """
        px = float(entry_price or 0.0)
        lev = max(1.0, float(leverage or 1.0))
        if px <= 0.0:
            raise ValueError("entry_price_must_be_positive")
        notional = float(budget_usdt) * lev
        qty = notional / px
        return round(qty, 8)

MAX_RISK_PER_TRADE_PCT = float(os.getenv("MAX_RISK_PER_TRADE_PCT", "1.0"))
MAX_DAILY_TRADES = int(os.getenv("MAX_DAILY_TRADES", "10"))
TRADE_COOLDOWN_SECONDS = int(os.getenv("TRADE_COOLDOWN_SECONDS", "1800"))
ACCOUNT_EQUITY_USDT = float(os.getenv("ACCOUNT_EQUITY_USDT", os.getenv("DEFAULT_ACCOUNT_EQUITY_USDT", "1000")))

_state_lock = threading.RLock()
_daily_state: Dict[str, Any] = {"date": None, "count": 0}
_last_trade_ts_global: float = 0.0
_last_trade_ts_per_symbol: Dict[str, float] = {}

def _today_str(now: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now or time.time()))

def _reset_daily_locked(now: float) -> None:
    today = _today_str(now)
    if _daily_state["date"] != today:
        _daily_state["date"] = today
        _daily_state["count"] = 0

def can_execute_trade(symbol: str, now: Optional[float] = None) -> Dict[str, Any]:
    """
    Checks daily limits and cooldown windows without mutating counters.
    """
    now_ts = now or time.time()
    with _state_lock:
        _reset_daily_locked(now_ts)
        if MAX_DAILY_TRADES > 0 and _daily_state["count"] >= MAX_DAILY_TRADES:
            remaining = max(0, MAX_DAILY_TRADES - _daily_state["count"])
            return {"ok": False, "reason": "max_daily", "remaining": remaining}
        if TRADE_COOLDOWN_SECONDS > 0 and _last_trade_ts_global:
            diff = now_ts - _last_trade_ts_global
            if diff < TRADE_COOLDOWN_SECONDS:
                return {"ok": False, "reason": "cooldown", "retry_after": int(TRADE_COOLDOWN_SECONDS - diff)}
        sym_last = _last_trade_ts_per_symbol.get(symbol.upper())
        if TRADE_COOLDOWN_SECONDS > 0 and sym_last:
            diff = now_ts - sym_last
            if diff < TRADE_COOLDOWN_SECONDS:
                return {"ok": False, "reason": "cooldown_symbol", "retry_after": int(TRADE_COOLDOWN_SECONDS - diff)}
    return {"ok": True}

def note_trade_execution(symbol: str, now: Optional[float] = None) -> None:
    """
    Records a trade execution (increments daily count + updates cooldown timestamps).
    """
    now_ts = now or time.time()
    with _state_lock:
        _reset_daily_locked(now_ts)
        _daily_state["count"] += 1
        if MAX_DAILY_TRADES > 0:
            _daily_state["count"] = min(_daily_state["count"], MAX_DAILY_TRADES)
        global _last_trade_ts_global
        _last_trade_ts_global = now_ts
        _last_trade_ts_per_symbol[symbol.upper()] = now_ts

def _estimate_risk_pct(entry_price: float, stop_price: Optional[float], qty: float) -> Optional[float]:
    if stop_price is None or stop_price <= 0 or qty <= 0 or entry_price <= 0 or ACCOUNT_EQUITY_USDT <= 0:
        return None
    risk_usd = abs(entry_price - float(stop_price)) * float(qty)
    if risk_usd <= 0:
        return 0.0
    return (risk_usd / ACCOUNT_EQUITY_USDT) * 100.0

def evaluate_trade_request(
    *,
    symbol: str,
    side: str,
    entry_price: Optional[float],
    stop_price: Optional[float],
    quantity: Optional[float],
    leverage: float,
    budget_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Estimate risk percentage for requested trade. Returns {"ok": bool, ...}.
    If data missing (no entry/stop), returns ok=True with reason.
    """
    try:
        entry = float(entry_price) if entry_price else None
    except Exception:
        entry = None
    stop = float(stop_price) if stop_price else None
    qty = quantity if quantity and quantity > 0 else None

    if entry is None or entry <= 0:
        try:
            from utils.binance_client import get_price_coalesced  # type: ignore
            entry = get_price_coalesced(symbol)
        except Exception:
            entry = None
    if entry is None or entry <= 0:
        return {"ok": True, "reason": "price_missing"}

    if qty is None:
        if budget_usd and budget_usd > 0:
            try:
                qty = calculate_quantity(
                    symbol=symbol,
                    entry_price=float(entry),
                    leverage=float(leverage or 1.0),
                    budget_usdt=float(budget_usd),
                )
            except Exception as exc:
                return {"ok": False, "reason": "qty_error", "detail": str(exc)}
        else:
            return {"ok": True, "reason": "qty_missing"}

    risk_pct = _estimate_risk_pct(float(entry), stop, float(qty))
    if risk_pct is not None and risk_pct > MAX_RISK_PER_TRADE_PCT:
        return {"ok": False, "reason": "risk_pct", "risk_pct": risk_pct}
    return {"ok": True, "risk_pct": risk_pct}

# ===== Public API =====
def choose_trade_budget(
    *,
    symbol: str,
    entry_price: Optional[float] = None,
    stop_price: Optional[float] = None,   # reserved
    quality_score: Optional[float] = None,
    atr: Optional[float] = None,
    price_hint: Optional[float] = None
) -> Dict[str, Any]:
    """
    בוחר תקציב טרייד (USDT) דינמי דרך utils.budget.get_trade_budget_usdt.
    """
    price_for_vol = float(entry_price) if entry_price else (float(price_hint) if price_hint else None)
    budget = float(get_trade_budget_usdt(
        symbol=symbol,
        quality=quality_score,
        atr=atr,
        price=price_for_vol
    ))
    return {"ok": budget > 0, "budget_usdt": round(budget, 2)}

def compute_position_size(
    *,
    symbol: str,
    side: str,
    entry_price: float,
    stop_price: Optional[float],
    leverage: float,
    quality_score: Optional[float] = None,
    atr: Optional[float] = None
) -> Dict[str, Any]:
    """
    - קובע תקציב (דינמי)
    - מחשב qty לפי התקציב, המחיר ודיוקי הסימבול.
    """
    bdg = choose_trade_budget(
        symbol=symbol,
        entry_price=entry_price,
        stop_price=stop_price,
        quality_score=quality_score,
        atr=atr,
    )
    if not bdg.get("ok"):
        return {"ok": False, "error": "budget_not_positive", "explain": bdg}

    budget = float(bdg["budget_usdt"])
    try:
        qty = calculate_quantity(
            symbol=symbol,
            entry_price=float(entry_price),
            leverage=float(leverage),
            budget_usdt=budget
        )
    except Exception as e:
        log.error("calculate_quantity error: %s", e)
        return {"ok": False, "error": str(e), "explain": bdg}

    risk_eval = evaluate_trade_request(
        symbol=symbol,
        side=side,
        entry_price=float(entry_price),
        stop_price=stop_price,
        quantity=qty,
        leverage=float(leverage),
        budget_usd=budget,
    )
    if not risk_eval.get("ok", True):
        detail = risk_eval.copy()
        detail.pop("ok", None)
        return {"ok": False, "error": detail.get("reason", "risk_blocked"), "detail": detail}

    return {
        "ok": True,
        "symbol": symbol.upper(),
        "side": str(side).upper(),
        "budget_usdt": round(budget, 2),
        "qty": qty,
        "entry_price": float(entry_price),
        "stop_price": float(stop_price) if stop_price else None,
        "leverage": float(leverage),
        "explain": bdg,
        "risk_pct": risk_eval.get("risk_pct"),
    }

def suggest_risk(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Shim תואם-ממשק לרואטרים ישנים: מחזיר המלצה בסיסית ובתקציב דינמי.
    לא מבצע אישור/ביצוע — אישורים מתבצעים רק דרך טלגרם (דינמי לפי ENV).
    """
    symbol = str(payload.get("symbol", "")).upper()
    entry = payload.get("entry") or payload.get("entry_price") or payload.get("price")
    sl = payload.get("sl") or payload.get("sl_price")
    lev = payload.get("leverage") or 10
    score = payload.get("score") or payload.get("quality") or None
    atr = payload.get("atr") or None

    bdg = choose_trade_budget(
        symbol=symbol,
        entry_price=float(entry) if entry else None,
        stop_price=float(sl) if sl else None,
        quality_score=float(score) if score is not None else None,
        atr=float(atr) if atr is not None else None,
    )
    try:
        out = {
            "ok": True,
            "suggestion": {
                "max_leverage": int(lev) if float(lev).is_integer() else float(lev),
                "budget": float(bdg.get("budget_usdt") or 0.0),
            },
            "explain": bdg,
        }
    except Exception:
        out = {"ok": True, "suggestion": {"max_leverage": 10, "budget": 25.0}, "explain": bdg}
    return out

__all__ = [
    "choose_trade_budget",
    "compute_position_size",
    "suggest_risk",
    "can_execute_trade",
    "note_trade_execution",
    "evaluate_trade_request",
]






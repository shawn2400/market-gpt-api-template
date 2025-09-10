# utils/risk.py
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
import math, os, logging

log = logging.getLogger("algogpt.risk")

# קונפיג בסיסי (נשלף אם קיים; אחרת דפ״ל בטוחים)
try:
    from utils import config
except Exception:
    class _C:
        RISK_PER_TRADE_PCT = 1.0
        MAX_LEVERAGE = 35
        MAX_TRADE_BUDGET = 100.0
    config = _C()

# נסיונות עדינים לשימוש בפילטרים מהבורסה (כימות + notional)
try:
    from utils.binance_client import get_symbol_filters as _get_symbol_filters  # type: ignore
except Exception:
    _get_symbol_filters = None  # type: ignore

DEFAULT_QTY_STEP = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))
DEFAULT_TICK     = float(os.getenv("DEFAULT_PRICE_TICK", "0.01"))
DEFAULT_MIN_NOT  = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

# Scaling לפי Confidence (0..1 או 0..10)
CONF_MUL_MIN = float(os.getenv("RISK_CONF_MIN_MULT", "0.6"))  # ב־0 confidence
CONF_MUL_MAX = float(os.getenv("RISK_CONF_MAX_MULT", "1.4"))  # ב־1/10 confidence

# Cap קשיח אם ATR% גבוה מאוד
ATR_PCT_SOFT_CAP = float(os.getenv("RISK_ATR_PCT_SOFT_CAP", "3.0"))  # אם >3% — הורדת מינוף קלה
ATR_PCT_SOFT_CAP_LEV = int(os.getenv("RISK_ATR_PCT_SOFT_CAP_LEV", "10"))

def _decimals(step_str: str) -> int:
    if "." not in step_str: return 0
    return len(step_str.split(".")[1].rstrip("0"))

def _filters(symbol: str) -> Dict[str, Any]:
    if _get_symbol_filters is None:
        return {}
    try:
        return _get_symbol_filters(symbol) or {}
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
    steps = math.floor(qty / step); q = max(step, steps * step)
    s = f"{q:.{decs}f}"; return s, float(s)

def _min_notional(symbol: str) -> float:
    f = _filters(symbol); mn = f.get("minNotional")
    try: return float(mn) if mn is not None else DEFAULT_MIN_NOT
    except Exception: return DEFAULT_MIN_NOT

def _ensure_min_notional(symbol: str, entry: float, qty: float) -> float:
    mn = _min_notional(symbol)
    if entry * qty >= mn: 
        return qty
    need = mn / max(entry, 1e-9)
    _, q2 = _q_qty(symbol, need)
    return q2

def _normalize_confidence(confidence: Optional[float]) -> Optional[float]:
    if confidence is None:
        return None
    try:
        c = float(confidence)
        if c <= 1.0:    # [0..1]
            return max(0.0, min(1.0, c))
        # כנראה [0..10]
        return max(0.0, min(1.0, c / 10.0))
    except Exception:
        return None

def _apply_confidence_scaling(base_pct: float, confidence: Optional[float]) -> float:
    cn = _normalize_confidence(confidence)
    if cn is None:
        return base_pct
    mul = CONF_MUL_MIN + (CONF_MUL_MAX - CONF_MUL_MIN) * cn
    # שמירה על גבולות סבירים (לא להגדיל מעל פי 2 ברוטאלי)
    mul = max(0.3, min(2.0, mul))
    return float(base_pct) * mul

def suggest_risk(
    symbol: str,
    side: str,
    entry: float,
    sl: float,
    tp: Optional[float] = None,
    atr: Optional[float] = None,                 # ATR אבסולוטי (ביחידות מחיר)
    equity_usdt: Optional[float] = None,
    confidence: Optional[float] = None,          # 0..1 או 0..10
    max_budget_usdt: Optional[float] = None,
    max_leverage: Optional[int] = None,
) -> Dict[str, Any]:
    """
    מחשב כמות, מינוף ובדג'ט מומלצים לפי RISK_PER_TRADE_PCT, עם:
      • התאמה עדינה לפי confidence (0..1/10) — סקייל ל-risk_pct.
      • בדיקת notional מינימלי וכימות לפי tick/step מסביבת הבורסה (אם זמין).
      • הורדת מינוף קלה אם ATR% גבוה (אופציונלי, ATR_PCT_SOFT_CAP).
    הפלט תואם אחורה ומוסיף שדות מועילים (qty_str/price_str/atr_pct/notes).
    """
    if entry <= 0 or sl <= 0:
        raise ValueError("entry/sl must be > 0")

    risk_pct_base = float(getattr(config, "RISK_PER_TRADE_PCT", 1.0))
    risk_pct = _apply_confidence_scaling(risk_pct_base, confidence)

    max_lev_cfg = int(max_leverage or getattr(config, "MAX_LEVERAGE", 35))
    budget_cap = float(max_budget_usdt or getattr(config, "MAX_TRADE_BUDGET", 100.0))

    base_amount = equity_usdt if equity_usdt and equity_usdt > 0 else budget_cap
    # risk_pct הוא אחוז → חלק את ב־100
    risk_usd = base_amount * (risk_pct / 100.0)

    dist = abs(entry - sl)
    if dist <= 0:
        raise ValueError("entry/sl distance must be > 0")

    # גודל פוזיציה לפי $סיכון
    qty = risk_usd / dist
    notion = qty * entry

    # כבודג'ט — אם notion חורג מתקרת התקציב, סקייל-דאון
    if notion > budget_cap:
        scale = budget_cap / max(notion, 1e-9)
        qty *= scale
        notion = qty * entry

    # מינוף ראשוני לפי יחס notion/risk
    lev = max(1, math.floor(notion / max(risk_usd, 1e-9)))

    # ATR% → cap קל על מינוף (לא חובה)
    atr_pct = None
    if atr is not None and entry > 0:
        try:
            atr_pct = abs(float(atr) / float(entry)) * 100.0
            if float(atr_pct) >= ATR_PCT_SOFT_CAP:
                lev = min(lev, ATR_PCT_SOFT_CAP_LEV)
        except Exception:
            atr_pct = None

    # Clamp מינוף למקסימום מערכת
    lev = min(lev, max_lev_cfg)

    # כימות ו־minNotional (אם אפשר)
    try:
        # הקפד על notional מינ' — העלאת qty אם צריך (כמות מינ' לפי step)
        qty = _ensure_min_notional(symbol, entry, qty)
        qty_str, qty = _q_qty(symbol, qty)
    except Exception:
        qty_str = f"{qty:.6f}"

    # RR (אם יש TP)
    rr = None
    if tp and tp > 0:
        reward = abs(tp - entry) * qty
        rr = reward / max(risk_usd, 1e-9)

    suggested = {
        "symbol": symbol,
        "side": side.upper(),
        "entry": float(entry),
        "sl": float(sl),
        "tp": float(tp) if tp else None,
        "leverage": int(lev),
        "budget_usdt": round(notion, 2),
        "qty": float(qty),
        "qty_str": qty_str,         # נוח לשימוש מידי בהזמנה
        "risk_usd": round(risk_usd, 2),
        "rr": rr,
    }

    out: Dict[str, Any] = {
        "ok": True,
        "suggested": suggested,
        "inputs": {
            "equity_usdt": equity_usdt,
            "risk_pct_base": risk_pct_base,
            "risk_pct_effective": risk_pct,
            "max_budget_usdt": budget_cap,
            "max_leverage": max_lev_cfg,
            "confidence": confidence,
            "atr": atr,
            "atr_pct": atr_pct,
        },
    }

    # הערות עזר (לא מחייב)
    notes: list[str] = []
    if confidence is not None:
        notes.append("confidence_scaling_applied")
    if atr_pct is not None and atr_pct >= ATR_PCT_SOFT_CAP:
        notes.append("atr_pct_soft_cap_on_leverage")
    if notes:
        out["notes"] = notes
    return out





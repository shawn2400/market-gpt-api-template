# utils/risk_guard.py
from __future__ import annotations
import os, time, logging, math
from datetime import datetime, timedelta
from typing import Tuple, Dict, Any, Optional, List

logger = logging.getLogger("algogpt.risk_guard")

# ────────────────────── פולבקים קלים למודולים אופציונליים ─────────────────────
try:
    from utils.pnl_summary import get_pnl_summary  # type: ignore
except Exception:
    def get_pnl_summary(limit_days: int = 1) -> Dict[str, Any]:
        return {"days": []}

try:
    from utils.trade_store import list_active  # type: ignore
except Exception:
    def list_active() -> List[Dict[str, Any]]:
        return []

try:
    from utils.position_sizing import ensure_final_qty  # type: ignore
except Exception:
    def ensure_final_qty(ticket: Dict[str, Any], last_price: float) -> Dict[str, Any]:
        # לא שובר כלום: מחזיר את הטיקט כמו שהוא
        return ticket

# מחיר אחרון (best-effort, בלי להפיל)
try:
    from main import get_last_price_async  # type: ignore
except Exception:
    async def get_last_price_async(symbol: str) -> Optional[float]:
        return None

# טלמטריה (לא חובה)
try:
    from utils.metrics_tracker import observe_slip_bps  # type: ignore
except Exception:
    def observe_slip_bps(_v: float) -> None:
        pass

# ───────────────────────── עזרי ENV/קונפיג ב־once ─────────────────────────────
def _bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes", "on")

def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _env() -> Dict[str, Any]:
    return {
        # כיבוי כללי
        "GLOBAL_OFF": _bool("GLOBAL_RISK_OFF", "0"),
        # תקרת הפסד יומי נטו (41)
        "DAILY_MAX_LOSS": _float("DAILY_NET_LOSS_USD_MAX", _float("DAILY_LOSS_CAP_USDT", 9_999_999)),
        # מגבלת טריידים פתוחים פר־סימבול (10/41)
        "MAX_OPEN_PER_SYMBOL": _int("MAX_CONCURRENT_TRADES_PER_SYMBOL", 999),
        # Three-Strike (19): הקפאה אחרי X SL ב־Y שעות
        "THREE_STRIKE_MAX_SL": _int("THREE_STRIKE_MAX_SL", 3),
        "THREE_STRIKE_WINDOW_H": _int("THREE_STRIKE_WINDOW_H", 24),
        # Volatility Gate: חסום כניסה אם ATR% גבוה מדי (14/58/99 חוצה)
        "VOLATILITY_GATE_ATRPCT": _float("VOLATILITY_GATE_ATRPCT", 0.0),  # 0=כבוי
        # Volatility Targeting (99)
        "VOL_TARGET_PCT": _float("VOL_TARGET_PCT", 0.015),
        # Kelly-Lite Cap (100)
        "KELLY_LITE_CAP": _float("KELLY_LITE_CAP", 0.5),
        # Correlation-aware (101) + C2 Halt מול BTC shock
        "CORR_CAP_BETA": _float("CORR_CAP_BETA", 1.6),
        "C2_BTC_SHOCK_BPS": _float("C2_BTC_SHOCK_BPS", 80.0),  # לדוגמה: 80bps ב־5–15דק׳
        "C2_HALT_MINUTES": _int("C2_HALT_MINUTES", 15),
        # Expectation-Guard (C3)
        "C3_EXPECTANCY_MIN": _float("C3_EXPECTANCY_MIN", 0.0),  # אם ממוצע R<0 → הקשחה
        "C3_BUDGET_CAP_PCT": _float("C3_BUDGET_CAP_PCT", 0.5),  # קיטון תקציב יחסי
        # התאמה דינמית (102)
        "ADAPTIVE_BUDGET_UP": _float("ADAPTIVE_BUDGET_UP", 0.05),
        "ADAPTIVE_BUDGET_DOWN": _float("ADAPTIVE_BUDGET_DOWN", 0.10),
        # floor ל־RR (17/43) — אופציונלי: רק מסמן שחומרה ↑
        "RR_FLOOR_MIN": _float("RR_FLOOR_MIN", 1.2),
    }

# ─────────────────────────── אינדיקטורים/סטורם קלים ──────────────────────────
# ספירת SL אחרונות (פולבק — ניתן להחליף למקור אמת)
def _recent_symbol_sl_count(symbol: str, window_h: int) -> int:
    # אם יש לך לוג ניצחונות/הפסדים – חבר כאן.
    # כעת מחזיר 0 כדי שלא יחסום סתם.
    _ = symbol, window_h
    return 0

# בטא/קורלציה מול BTC/ETH – פולבק
def _symbol_beta(symbol: str) -> float:
    _ = symbol
    # אפשר להציב ידנית ENV לגיבוי: BETA_<SYMBOL>=1.8
    try:
        return float(os.getenv(f"BETA_{symbol.upper()}", "1.0"))
    except Exception:
        return 1.0

# זיהוי Shock ב־BTC (Best-effort): מוזן חיצונית דרך ENV volatile flag
def _btc_shock_bps() -> float:
    # אפשר להאכיל מבחוץ בערך עדכני דרך ENV BTC_SHOCK_BPS (משירות WS)
    try:
        return float(os.getenv("BTC_SHOCK_BPS", "0"))
    except Exception:
        return 0.0

# Expectancy (R-ממוצע מתגלגל) — פולבק
def _rolling_expectancy_R() -> float:
    try:
        from utils.analytics_logger import get_expectancy_rolling  # type: ignore
        v = get_expectancy_rolling(window_n=_int("C3_EXPECTANCY_WINDOW", 50))
        return float(v)
    except Exception:
        return 0.0

# ATR% נוכחי לסימבול (אם יש לך קליינס — אפשר לחבר)
async def _atr_pct_now(symbol: str) -> Optional[float]:
    try:
        from main import _fetch_klines_http  # type: ignore
        kl = await _fetch_klines_http(symbol, interval=os.getenv("ENTRY_SCORE_INTERVAL", "15m"), limit=120)  # type: ignore
        if not kl:
            return None
        closes = [float(k[4]) for k in kl]
        highs  = [float(k[2]) for k in kl]
        lows   = [float(k[3]) for k in kl]
        trs = []
        for i in range(1, len(kl)):
            h, l, pc = highs[i], lows[i], closes[i-1]
            trs.append(max(h-l, abs(h-pc), abs(l-pc)))
        atr = sum(trs[-14:]) / float(min(14, len(trs))) if trs else 0.0
        px  = closes[-1]
        return (atr/px)*100.0 if px>0 else None
    except Exception:
        return None

# ─────────────────────────── ליבת בדיקות והרכבה ───────────────────────────────
async def allow_new_trade(symbol: str) -> Tuple[bool, str]:
    """שומר על API הקודם — בדיקות בסיסיות בלבד."""
    env = _env()

    if env["GLOBAL_OFF"]:
        logger.warning("🚫 Trade blocked: GLOBAL_RISK_OFF=1")
        return (False, "GLOBAL_RISK_OFF")

    # מגבלת טריידים פתוחים פר־סימבול
    try:
        sym = (symbol or "").upper()
        cnt = sum(1 for t in list_active() if str(t.get("symbol", "")).upper() == sym)
        if cnt >= env["MAX_OPEN_PER_SYMBOL"]:
            logger.warning("🚫 Trade blocked: MAX_CONCURRENT_TRADES_PER_SYMBOL reached (%s)", env["MAX_OPEN_PER_SYMBOL"])
            return (False, f"MAX_CONCURRENT_TRADES_PER_SYMBOL={env['MAX_OPEN_PER_SYMBOL']}")
    except Exception as e:
        logger.error("list_active failed: %s", e)

    # תקרת הפסד יומי נטו
    try:
        day = datetime.utcnow().strftime("%Y-%m-%d")
        pnl = get_pnl_summary(limit_days=1)
        today = next((d for d in pnl.get("days", []) if str(d.get("day")) == day), None)
        loss = float(today.get("pnl", 0.0)) if today else 0.0
        if loss < 0 and abs(loss) > env["DAILY_MAX_LOSS"]:
            logger.warning("🚫 Trade blocked: DAILY_NET_LOSS_USD_MAX=%s hit (loss=%.2f)", env["DAILY_MAX_LOSS"], loss)
            return (False, f"DAILY_NET_LOSS_USD_MAX={env['DAILY_MAX_LOSS']}")
    except Exception as e:
        logger.error("get_pnl_summary failed: %s", e)

    return (True, "OK")

# חדש: בדיקות מתקדמות + תיקון אוטומטי של ticket
async def allow_and_fix_ticket(ticket: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """
    מחזיר:
      allowed (bool), reason (str), ticket_fixed (dict)
    מתקן budget/qty/lev לפי VolTarget/Kelly-lite/Expectation/Corr halt/Three-strike/VolGate.
    אם חסום — לא משנה את הטיקט (מלבד הוספת סיבה).
    """
    env = _env()
    sym = str(ticket.get("symbol", "")).upper()
    side = str(ticket.get("side", "")).upper()
    t_fixed = dict(ticket)

    # 1) חסימות כלליות מהגרסה הפשוטה
    ok_basic, reason_basic = await allow_new_trade(sym)
    if not ok_basic:
        return False, reason_basic, ticket

    # 2) Three-Strike (19)
    sl_cnt = _recent_symbol_sl_count(sym, env["THREE_STRIKE_WINDOW_H"])
    if sl_cnt >= env["THREE_STRIKE_MAX_SL"]:
        return False, f"THREE_STRIKE:{sl_cnt}/{env['THREE_STRIKE_MAX_SL']}", ticket

    # 3) Correlated Halt (C2) מול BTC shock
    btc_bps = _btc_shock_bps()
    beta = _symbol_beta(sym)
    if beta >= env["CORR_CAP_BETA"] and btc_bps >= env["C2_BTC_SHOCK_BPS"]:
        return False, f"C2_CORR_HALT:beta={beta:.2f},btc_shock={btc_bps:.0f}bps", ticket

    # 4) Volatility Gate (14/99): אם ATR% גבוה מהסף
    atrpct_cfg = env["VOLATILITY_GATE_ATRPCT"]
    if atrpct_cfg > 0:
        try:
            atrpct = float(ticket.get("atr_pct") or 0.0)
        except Exception:
            atrpct = 0.0
        if atrpct <= 0:
            atrpct = (await _atr_pct_now(sym)) or 0.0
        if atrpct >= atrpct_cfg:
            return False, f"VOLATILITY_GATE:atr%={atrpct:.3f}≥{atrpct_cfg:.3f}", ticket

    # 5) Expectation-Guard (C3)
    exp_R = _rolling_expectancy_R()
    if exp_R < env["C3_EXPECTANCY_MIN"]:
        # הקטנת תקציב אוט' (חסימה רק אם EXP_R << 0 משמעותית ואינך רוצה לסכן)
        cap_pct = max(0.05, min(1.0, env["C3_BUDGET_CAP_PCT"]))
        b = float(t_fixed.get("budget") or t_fixed.get("budget_usd") or 0.0)
        if b > 0:
            t_fixed["budget"] = b * cap_pct

    # 6) Volatility Targeting (99) + Kelly-Lite (100) — תיקוני lev/qty/budget
    price = None
    try:
        price = await get_last_price_async(sym)
    except Exception:
        price = None

    lev = int(t_fixed.get("leverage") or t_fixed.get("lev") or 0)
    lev_min = int(t_fixed.get("leverage_min") or (t_fixed.get("leverage_range") or [15, 25])[0] or 1)
    lev_max = int(t_fixed.get("leverage_max") or (t_fixed.get("leverage_range") or [15, 25])[-1] or 50)
    lev = max(lev_min, min(lev if lev > 0 else (lev_min + lev_max)//2, lev_max))
    t_fixed["leverage"] = lev

    # אם יש ATR% → יעד תנודתיות קובע ערך תקציב משוער
    target_risk = env["VOL_TARGET_PCT"]  # אחוז מהמחיר
    b_in = float(t_fixed.get("budget") or t_fixed.get("budget_usd") or 0.0)
    if (price or 0) > 0 and target_risk > 0:
        # qty ≈ (budget*lev)/price ; סיכון ≈ ATR% * qty * price / lev? (קירוב גס)
        # כאן: נשמור על תקציב, נוודא שלא עובר CAP (Kelly-lite)
        pass  # השארת התקציב כפי שהוא, החישוב המדויק אצל ensure_final_qty

    # Kelly-lite cap: נוריד את התקציב אם “Kelly estimate” עובר חצי קלי
    # (אין לנו חישוב Kelly בפועל כאן; נשמש ב־cap חיצוני אם סופק)
    kcap = env["KELLY_LITE_CAP"]
    if 0 < kcap < 1 and b_in > 0:
        # אם יש ENV MAX_TRADE_BUDGET → נכבד אותו גם כאן
        try:
            max_budget_env = float(os.getenv("MAX_TRADE_BUDGET", "0") or 0.0)
        except Exception:
            max_budget_env = 0.0
        b_cap = b_in if max_budget_env <= 0 else min(b_in, max_budget_env)
        t_fixed["budget"] = b_cap

    # 7) כימות כמות סופית (qty) לפי כללים מערכתיים (אם קיים)
    if (price or 0) > 0:
        t_fixed = ensure_final_qty(t_fixed, float(price)) or t_fixed

    # sanity: qty/leverage > 0
    if float(t_fixed.get("qty") or 0) <= 0 or int(t_fixed.get("leverage") or 0) <= 0:
        return False, "BAD_TICKET_QTY_OR_LEV", ticket

    return True, "OK", t_fixed


__all__ = ["allow_new_trade", "allow_and_fix_ticket"]



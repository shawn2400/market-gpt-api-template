# routes/scan_top_volume.py
from __future__ import annotations

import os
import time
import logging
from typing import Optional, Dict, Any, List, Tuple

from fastapi import APIRouter, Query, Depends

LOG = logging.getLogger("algogpt.scan")

# --- auth (fallback בטוח) ---
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

# --- notifier: שליחת "אישור טרייד" עשירה לטלגרם ---
try:
    from utils.telegram_notifier import send_trade_approval  # type: ignore
except Exception:
    async def send_trade_approval(idem: str, plan: Dict[str, Any], chat_id: Optional[int] = None) -> None:
        return None

# --- טקסט פשוט (Heartbeat/בדיקות) ---
try:
    from utils.telegram_notifier_core import _tg_send as _tg_send_text  # type: ignore
except Exception:
    async def _tg_send_text(text: str, chat_id: Optional[int] = None) -> None:
        return None

# --- דאטה שוק (klines/price) ---
try:
    from utils.get_klines import get_klines_sync  # type: ignore
except Exception:
    get_klines_sync = None  # type: ignore


router = APIRouter(prefix="/scan", tags=["scan"], dependencies=[Depends(require_bearer_token)])

# --- זיכרון קטן למניעת ספאם (per symbol+timeframe) ---
_STATE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_LAST_GOOD_TS = 0.0
_ALLOWED_NOTIFY = {"telegram", None}


# ============================
# Helpers
# ============================

def _get_env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except Exception:
        return default

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def _parse_score_equity_table(raw: str) -> List[Tuple[float, float]]:
    """
    מחרוזת: "6.5:0.6,7:0.9,7.5:1.1,8:1.3,8.5:1.7,9:2.0,9.5:2.5"
    => [(score_thresh, pct_equity), ...] ממוין. pct=אחוז מההון (1.3 => 1.3%).
    """
    out: List[Tuple[float, float]] = []
    raw = (raw or "").strip()
    if not raw:
        return out
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    for p in parts:
        try:
            k, v = p.split(":")
            out.append((float(k.strip()), float(v.strip())))
        except Exception:
            continue
    out.sort(key=lambda x: x[0])
    return out

def _score_to_equity_pct(score: float, table: List[Tuple[float, float]], fallback_pct: float) -> float:
    pct = fallback_pct
    for thr, p in table:
        if score >= thr:
            pct = p
        else:
            break
    return pct

def _safe_get_price(symbol: str) -> float:
    # 1) utils.binance_client
    try:
        from utils.binance_client import get_price  # type: ignore
        p = get_price(symbol)
        if p:
            return float(p)
    except Exception:
        pass
    # 2) python-binance futures ticker (אם יש מפתחות)
    try:
        from binance.client import Client  # type: ignore
        api_key = os.getenv("BINANCE_API_KEY", "").strip()
        api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
        if not api_key or not api_sec:
            return 0.0
        cli = Client(api_key, api_sec)
        info = cli.futures_symbol_ticker(symbol=str(symbol).upper())
        if info and "price" in info:
            return float(info["price"])
    except Exception as e:
        LOG.debug({"event": "price.fallback_failed", "symbol": symbol, "error": str(e)})
    return 0.0


# ============================
# Auto Risk (Leverage + Stake %Equity) — דינמי חי
# ============================

def _auto_risk(
    *,
    score_total: Optional[float],
    adx: Optional[float],
    atr_pct: Optional[float],
    equity_usdt: Optional[float] = None,
    default_leverage: float = 10.0,
    default_stake_usdt: float = 50.0,
) -> Tuple[float, float]:
    """
    מחזיר (leverage, stake_usdt) דינמי לגמרי:
      - stake_usdt = סכום נטו ב-USD מתוך ההון (לא קשור למינוף).
      - אחוז ההון נגזר מטבלת ציון→%, מוכפל במכפיל דינמי לפי ADX/ATR/דרואודאון/משטר שוק.
      - Safe Fraction (כרית ביטחון) דינמי.
      - מינוף מותאם ADX/ATR עם קלמפים קשיחים.
    """
    enabled = (os.getenv("AUTO_RISK_ENABLE", "1") or "1").strip() == "1"

    # בסיסים וקלמפים
    lev_base = _get_env_float("RISK_LEV_BASE", default_leverage)
    lev_min  = _get_env_float("RISK_LEV_MIN",  5.0)
    lev_max  = _get_env_float("RISK_LEV_MAX", 15.0)

    pct_min  = _get_env_float("RISK_STAKE_EQUITY_MIN_PCT", 0.3)   # %
    pct_max  = _get_env_float("RISK_STAKE_EQUITY_MAX_PCT", 2.5)   # %
    stake_min = _get_env_float("RISK_STAKE_MIN_USDT", 25.0)
    stake_max = _get_env_float("RISK_STAKE_MAX_USDT", 500.0)

    # טבלת ציון→% בסיסית
    table_raw = os.getenv("RISK_SCORE_TO_EQUITY_PCT", "6.5:0.6,7:0.9,7.5:1.1,8:1.3,8.5:1.7,9:2.0,9.5:2.5")
    table = _parse_score_equity_table(table_raw)

    # טריגרים בסיסיים
    adx_strong = _get_env_float("RISK_ADX_STRONG", 35.0)
    adx_weak   = _get_env_float("RISK_ADX_WEAK",   20.0)
    atr_hi     = _get_env_float("RISK_ATR_HIGH_PCT", 4.0)
    atr_lo     = _get_env_float("RISK_ATR_LOW_PCT",  0.7)

    # בוסטרים/קאט בסיסיים
    stake_boost_strong = _get_env_float("RISK_STAKE_BOOST_STRONG_PCT", 15.0) / 100.0
    stake_cut_high_atr = _get_env_float("RISK_STAKE_CUT_HIGH_ATR_PCT",  20.0) / 100.0
    lev_boost_strong   = _get_env_float("RISK_LEV_BOOST_STRONG_PCT",   10.0) / 100.0
    lev_cut_high_atr   = _get_env_float("RISK_LEV_CUT_HIGH_ATR_PCT",   20.0) / 100.0

    # “הגדלה” בטריידים חזקים במיוחד
    extra_mode   = (os.getenv("RISK_EXTRA_ADD_MODE", "pct") or "pct").lower()  # "pct"|"usd"
    extra_thresh = _get_env_float("RISK_EXTRA_ADD_THRESH", 9.0)
    extra_value  = _get_env_float("RISK_EXTRA_ADD_VALUE",  25.0)

    # כוונון אוטומטי (מצב שוק/דרואודאון)
    tune_on   = (os.getenv("AUTO_RISK_TUNE_ENABLE", "1") or "1") == "1"
    adx_hi    = _get_env_float("TUNE_ADX_HIGH", 35.0)
    adx_lo    = _get_env_float("TUNE_ADX_LOW",  20.0)
    atr_hi_t  = _get_env_float("TUNE_ATR_HIGH", 4.0)
    atr_lo_t  = _get_env_float("TUNE_ATR_LOW",  0.7)

    tbl_mult_low  = _get_env_float("TUNE_TABLE_MULT_LOW",  0.90)
    tbl_mult_norm = _get_env_float("TUNE_TABLE_MULT_NORM", 1.00)
    tbl_mult_high = _get_env_float("TUNE_TABLE_MULT_HIGH", 1.20)

    sf_low   = _get_env_float("TUNE_SAFE_FRAC_LOW",  0.78)
    sf_norm  = _get_env_float("TUNE_SAFE_FRAC_NORM", 0.85)
    sf_high  = _get_env_float("TUNE_SAFE_FRAC_HIGH", 0.90)

    # דרואודאון אופציונלי
    dd_str = (os.getenv("DRAWDOWN_PCT", "") or "").strip()
    dd = float(dd_str) if dd_str else None
    dd_weak_at = _get_env_float("TUNE_DD_WEAKEN_AT", 5.0)
    dd_hard_at = _get_env_float("TUNE_DD_HARD_AT", 10.0)
    dd_tbl_weak = _get_env_float("TUNE_DD_TABLE_MULT_WEAK", 0.85)
    dd_tbl_hard = _get_env_float("TUNE_DD_TABLE_MULT_HARD", 0.70)
    dd_sf_bump_weak = _get_env_float("TUNE_DD_SAFE_FRAC_BUMP_WEAK", 0.05)
    dd_sf_bump_hard = _get_env_float("TUNE_DD_SAFE_FRAC_BUMP_HARD", 0.10)

    # אם לא מופעל — החזר בסיס
    if not enabled:
        lev = _clamp(lev_base, lev_min, lev_max)
        stake = _clamp(default_stake_usdt, stake_min, stake_max)
        return round(lev, 2), round(stake, 2)

    # ===== קביעת “Bucket” מצב שוק + סקייל אגרסיבי/שמרני אוטומטי =====
    def _bucket(adx_val: Optional[float], atr_val: Optional[float]) -> str:
        if adx_val is None or atr_val is None:
            return "norm"
        if adx_val >= adx_hi and atr_lo_t <= atr_val <= atr_hi_t:
            return "high"   # טרנד חזק, תנודתיות סבירה
        if adx_val <= adx_lo or atr_val >= atr_hi_t:
            return "low"    # טרנד חלש או תנודתיות גבוהה מדי
        return "norm"

    bucket = _bucket(adx, atr_pct)

    # סקייל רציף עוד יותר: אם ADX ממש גבוה, נרים את table_mult_high עד 1.30; אם ADX נמוך מאוד או ATR גבוה מאוד — נרד עד 0.80
    dynamic_high_cap = 1.30 if (adx is not None and adx >= (adx_hi + 5)) else tbl_mult_high
    dynamic_low_floor = 0.80 if (adx is not None and (adx <= (adx_lo - 3) or (atr_pct is not None and atr_pct >= (atr_hi_t + 1)))) else tbl_mult_low

    table_mult = {"low": dynamic_low_floor, "norm": tbl_mult_norm, "high": dynamic_high_cap}[bucket]
    safe_frac  = {"low": sf_low,            "norm": sf_norm,       "high": sf_high}[bucket]

    # החמרה לפי דרואודאון
    if tune_on and dd is not None:
        if dd >= dd_hard_at:
            table_mult *= dd_tbl_hard
            safe_frac  = min(0.98, safe_frac + dd_sf_bump_hard)
        elif dd >= dd_weak_at:
            table_mult *= dd_tbl_weak
            safe_frac  = min(0.95, safe_frac + dd_sf_bump_weak)

    # ===== חישוב Stake לפי Equity =====
    # Equity מה-ENV (אופציונלי). אם ריק → נופל ל-default stake.
    eq_env = os.getenv("ACCOUNT_EQUITY_USDT", "").strip()
    if equity_usdt is None and eq_env:
        try:
            equity_usdt = float(eq_env)
        except Exception:
            equity_usdt = None

    if equity_usdt and equity_usdt > 0:
        base_pct = _score_to_equity_pct(float(score_total or 0.0), table, fallback_pct=1.0)
        dyn_pct  = _clamp(base_pct * (table_mult if tune_on else 1.0), pct_min, pct_max)
        eff_equity = equity_usdt * _clamp(safe_frac, 0.5, 0.98)
        stake = eff_equity * (dyn_pct / 100.0)
    else:
        stake = default_stake_usdt

    # ===== מינוף: בסיס + בוסטרים/קאט =====
    lev = lev_base
    if adx is not None:
        if adx >= adx_strong:
            lev *= (1.0 + lev_boost_strong)
        elif adx <= adx_weak:
            lev *= 0.9
            stake *= 0.9

    if atr_pct is not None:
        if atr_pct >= atr_hi:
            lev *= (1.0 - lev_cut_high_atr)
            stake *= (1.0 - stake_cut_high_atr)
        elif atr_pct <= atr_lo:
            stake *= 0.95

    # הגדלה בטריידים חזקים במיוחד
    if score_total is not None and score_total >= extra_thresh:
        if extra_mode == "pct":
            stake *= (1.0 + (extra_value / 100.0))
        else:
            stake += extra_value

    # ===== קלמפים =====
    lev = _clamp(lev, lev_min, lev_max)
    stake = _clamp(stake, stake_min, stake_max)
    return round(lev, 2), round(stake, 2)


def _passes(sig: Dict[str, Any], min_score: float, require_side: bool) -> bool:
    try:
        score = float(sig.get("score_total") or sig.get("score") or 0)
    except Exception:
        score = 0.0
    side = (sig.get("side") or "").upper()
    return (score >= float(min_score or 0)) and ((not require_side) or (side in ("BUY", "SELL")))

def _should_notify(sig: Dict[str, Any], min_score: float, rearm_score: float, dedupe_window_sec: int) -> bool:
    symbol = str(sig.get("symbol") or "").upper() or "?"
    timeframe = str(sig.get("timeframe") or "").lower() or "?"
    key = (symbol, timeframe)

    now = time.time()
    st = _STATE.get(key) or {"state": "disarmed", "last_ts": 0.0, "last_score": 0.0}
    try:
        score = float(sig.get("score_total") or sig.get("score") or 0)
    except Exception:
        score = 0.0

    changed = False
    if st["state"] == "disarmed":
        if score >= min_score:
            st["state"] = "armed"
            changed = True
    else:
        if score < rearm_score:
            st["state"] = "disarmed"

    recently = (now - float(st.get("last_ts") or 0.0)) < max(0, int(dedupe_window_sec or 0))
    st["last_ts"] = now
    st["last_score"] = score
    _STATE[key] = st
    return changed and not recently

async def _heartbeat_if_needed(chat_id: Optional[str], notify: Optional[str],
                               min_score: float, found_filtered: bool) -> None:
    """
    שולח Heartbeat אם לא נמצאו טריידים מעל הסף במשך HEARTBEAT_HOURS.
    לא זורק חריגות — “כשל בטוח”.
    """
    global _LAST_GOOD_TS
    try:
        hb_hours = float(os.getenv("HEARTBEAT_HOURS", "0") or 0)
    except Exception:
        hb_hours = 0.0

    if hb_hours <= 0 or notify != "telegram" or not chat_id:
        return

    now = time.time()
    if found_filtered:
        _LAST_GOOD_TS = now
        return

    if _LAST_GOOD_TS == 0.0:
        _LAST_GOOD_TS = now
        return

    if (now - _LAST_GOOD_TS) >= hb_hours * 3600:
        try:
            low = float(os.getenv("HEARTBEAT_MIN_SCORE", "4.0"))
        except Exception:
            low = 4.0

        age_min = int((now - _LAST_GOOD_TS) // 60)
        txt = (
            'בס"ד\n'
            f"ℹ️ Heartbeat: לא נמצאו טריידים ≥ {min_score} מזה ~{age_min} ד׳.\n"
            f"נרשמו רק ציונים נמוכים יותר (למשל ~{low}-{max(low, min_score - 0.5):.1f}).\n"
            "_בעזרת השם נעשה ונצליח_ 🙏"
        )
        try:
            cid = int(chat_id)
        except Exception:
            cid = None

        try:
            await _tg_send_text(txt, chat_id=cid)
        except Exception as e:
            LOG.warning({"event": "heartbeat.send_failed", "error": str(e)})
        finally:
            _LAST_GOOD_TS = now


@router.get("/top-volume", summary="Scan (real data only) with post-filter, notify/TTL/heartbeat")
async def scan_top_volume(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    # פוסט־פילטר — ברירת מחדל: כל האיתותים
    min_score: float = Query(0.0),
    require_side: bool = Query(False),
    # התראות:
    notify: Optional[str] = Query(None, description="currently supported: 'telegram'"),
    chat_id: Optional[str] = Query(None),
    rich: bool = Query(True),
    ttl_sec: int = Query(900, ge=60, le=86400),
    rearm_score: float = Query(6.0),
    dedupe_window_sec: int = Query(300, ge=0, le=3600),
    # כלכלה (ברירות מחדל; ישוכתבו דינמית ב-Auto-Risk):
    leverage: float = Query(float(os.getenv("DEFAULT_LEVERAGE", "10"))),
    stake_usdt: float = Query(float(os.getenv("DEFAULT_STAKE_USDT", "50"))),
):
    """
    סורק ומחזיר *כל* האיתותים (אמיתי בלבד, בלי דמו), עם score_total=1..10 + רכיבים + ADX.
    אם אין דאטה — ok=false ו-error, signals=[]
    """
    if notify not in _ALLOWED_NOTIFY:
        LOG.warning({"event": "notify.unsupported", "notify": notify})
        notify = None

    err: Optional[str] = None
    signals_raw: List[Dict[str, Any]] = []
    try:
        signals_raw = await _compute_signals(market, quote, limit, timeframe, kline_limit)
        if not isinstance(signals_raw, list):
            raise TypeError("signals_raw is not a list")
    except Exception as e:
        err = f"compute_signals_failed: {e}"
        LOG.warning({"event": "scan.compute_failed", "error": str(e)})

    try:
        filtered = [s for s in (signals_raw or []) if isinstance(s, dict) and _passes(s, min_score, require_side)]
    except Exception as e:
        err = f"filter_failed: {e}"
        LOG.warning({"event": "scan.filter_failed", "error": str(e)})
        filtered = []

    LOG.info({
        "event": "scan.result",
        "requested": {"limit": limit, "tf": timeframe, "k": kline_limit, "min_score": min_score, "require_side": require_side},
        "counts": {"total": len(signals_raw or []), "returned": len(filtered)},
    })

    notified = 0
    if notify == "telegram" and chat_id and filtered:
        try:
            cid = int(chat_id)
        except Exception:
            cid = None
        for s in filtered:
            try:
                if _should_notify(s, max(min_score, 7.0), rearm_score, dedupe_window_sec):
                    det = (s.get("details") or {})
                    adx_val = det.get("adx")
                    atr_val = det.get("atr_pct")
                    score_val = s.get("score_total")

                    # Equity אופציונלי מה-ENV (אם זמין)
                    eq_env = os.getenv("ACCOUNT_EQUITY_USDT", "").strip()
                    equity = float(eq_env) if eq_env else None

                    # === Auto-Risk (leverage + stake %equity, דינמי) ===
                    dyn_lev, dyn_stake = _auto_risk(
                        score_total=score_val,
                        adx=adx_val,
                        atr_pct=atr_val,
                        equity_usdt=equity,
                        default_leverage=leverage,
                        default_stake_usdt=stake_usdt,
                    )

                    plan: Dict[str, Any] = {
                        "symbol": s.get("symbol"),
                        "side": s.get("side"),
                        "score": s.get("score_total"),
                        "timeframe": s.get("timeframe") or timeframe,
                        "order_type": "MARKET",
                        "entry_price": (s.get("details", {}) or {}).get("close"),
                        "sl": {"stopPrice": None},
                        "tp": [],
                        "budget_usd": dyn_stake,
                        "leverage": dyn_lev,
                        "ttl_sec": ttl_sec,
                        "why": s.get("note") or (s.get("details", {}) or {}).get("trend") or "—",
                        "rich": bool(rich),
                    }
                    idem = f"{(plan['symbol'] or '?')}-{(plan['timeframe'] or timeframe)}-{int(time.time())}"
                    try:
                        await send_trade_approval(idem, plan, chat_id=cid)
                        notified += 1
                    except Exception as ne:
                        LOG.warning({"event": "notify.send_failed", "symbol": plan.get("symbol"), "error": str(ne)})
            except Exception as loop_e:
                LOG.warning({"event": "notify.loop_failed", "error": str(loop_e)})

    try:
        await _heartbeat_if_needed(chat_id, notify, max(min_score, 7.0), found_filtered=bool(filtered))
    except Exception as hb_e:
        LOG.warning({"event": "heartbeat.failed", "error": str(hb_e)})

    return {
        "ok": err is None,
        "count_total": len(signals_raw or []),
        "returned": len(filtered),
        "notified": notified,
        "signals": filtered if filtered else (signals_raw or []),
        "mode": "full",
        "error": err,
    }


@router.get("/now", summary="Alias to /scan/top-volume (real data only)")
async def scan_now(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    min_score: float = Query(0.0),
    require_side: bool = Query(False),
    notify: Optional[str] = Query(None),
    chat_id: Optional[str] = Query(None),
    rich: bool = Query(True),
    ttl_sec: int = Query(900, ge=60, le=86400),
    rearm_score: float = Query(6.0),
    dedupe_window_sec: int = Query(300, ge=0, le=3600),
    leverage: float = Query(float(os.getenv("DEFAULT_LEVERAGE", "10"))),
    stake_usdt: float = Query(float(os.getenv("DEFAULT_STAKE_USDT", "50"))),
    symbol: Optional[str] = Query(None),  # תאימות לאחור; לא בשימוש
):
    return await scan_top_volume(
        market=market,
        quote=quote,
        limit=limit,
        timeframe=timeframe,
        kline_limit=kline_limit,
        min_score=min_score,
        require_side=require_side,
        notify=notify,
        chat_id=chat_id,
        rich=rich,
        ttl_sec=ttl_sec,
        rearm_score=rearm_score,
        dedupe_window_sec=dedupe_window_sec,
        leverage=leverage,
        stake_usdt=stake_usdt,
    )


# -------- מחשב איתותים: אמיתי בלבד (אין fallback דמו) + ADX --------
async def _compute_signals(market: str, quote: str, limit: int, timeframe: str, kline_limit: int) -> List[Dict[str, Any]]:
    """
    מביא klines אמיתיים ומחשב score_total=1..10 + פירוק components.
    Trend-Aggressive עם ADX: משקל גבוה ל-EMA gap, ענישת ATR קשיחה יותר,
    ואכיפת סף ADX_MIN על הכיוון/ציון.
    """
    import statistics
    out: List[Dict[str, Any]] = []

    def _rsi(closes: List[float], period: int = 14) -> Optional[float]:
        if len(closes) < period + 1:
            return None
        gains, losses = [], []
        for i in range(1, period + 1):
            ch = closes[-i] - closes[-i-1]
            gains.append(max(ch, 0.0))
            losses.append(abs(min(ch, 0.0)))
        avg_gain = statistics.fmean(gains) if any(gains) else 0.0
        avg_loss = statistics.fmean(losses) if any(losses) else 0.0
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / (avg_loss or 1e-9)
        return 100.0 - (100.0 / (1.0 + rs))

    def _ema(seq: List[float], n: int) -> float:
        if not seq:
            return 0.0
        k = 2 / (n + 1)
        ema = seq[0]
        for v in seq[1:]:
            ema = v * k + ema * (1 - k)
        return ema

    def _atr_pct_from_raw(rows: List[List[float]], period: int = 14) -> Optional[float]:
        if len(rows) < period + 1:
            return None
        trs = []
        prev_close = float(rows[-period-1][4])
        for r in rows[-period:]:
            h = float(r[2]); l = float(r[3]); c = float(r[4])
            tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
            trs.append(tr)
            prev_close = c
        atr = statistics.fmean(trs)
        last_close = float(rows[-1][4])
        if last_close <= 0:
            return None
        return (atr / last_close) * 100.0  # אחוז

    # Wilder's ADX (+DI/-DI) — הערכה מיידית
    def _adx_from_raw(rows: List[List[float]], period: int = 14) -> Optional[Dict[str, float]]:
        if len(rows) < period + 2:
            return None
        trs, dm_plus, dm_minus = [], [], []
        for i in range(1, period + 1):
            h1, l1, c1 = float(rows[-i][2]), float(rows[-i][3]), float(rows[-i][4])
            h0, l0, c0 = float(rows[-i-1][2]), float(rows[-i-1][3]), float(rows[-i-1][4])
            up = h1 - h0
            dn = l0 - l1
            dm_plus.append(up if (up > dn and up > 0) else 0.0)
            dm_minus.append(dn if (dn > up and dn > 0) else 0.0)
            tr = max(h1 - l1, abs(h1 - c0), abs(l1 - c0))
            trs.append(tr)

        def _avg(seq: List[float]) -> float:
            return statistics.fmean(seq) if seq else 0.0

        tr14 = _avg(trs)
        plus_dm14 = _avg(dm_plus)
        minus_dm14 = _avg(dm_minus)
        if tr14 <= 0:
            return None
        plus_di = 100.0 * (plus_dm14 / tr14)
        minus_di = 100.0 * (minus_dm14 / tr14)
        diff = abs(plus_di - minus_di)
        summ = plus_di + minus_di if (plus_di + minus_di) != 0 else 1e-9
        dx = 100.0 * (diff / summ)
        adx = dx
        return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}

    # universe
    wl = os.getenv("WATCHLIST", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
    wl = [s.strip().upper() for s in wl if s.strip()]
    wl = wl[:max(5, min(limit, 100))]

    tf = timeframe or "15m"
    k = max(60, min(kline_limit, 1000))
    max_atr_pct = float(os.getenv("MAX_ATR_PCT", "3"))
    adx_min = float(os.getenv("ADX_MIN", "20"))

    if get_klines_sync is None:
        raise RuntimeError("get_klines_sync unavailable")

    for sym in wl:
        try:
            df = get_klines_sync(sym, interval=tf, limit=k)

            closes: List[float]
            raw_rows: Optional[List[List[float]]] = None

            # DataFrame
            if hasattr(df, "__getitem__") and "close" in getattr(df, "columns", []):
                closes = [float(x) for x in df["close"]]
                if "high" in df.columns and "low" in df.columns:
                    raw_rows = [[None, None, float(h), float(l), float(c)]
                                for h, l, c in zip(df["high"][-k:], df["low"][-k:], df["close"][-k:])]
            # List[List]
            elif isinstance(df, list) and len(df) > 0:
                closes = [float(row[4]) for row in df]
                raw_rows = df
            else:
                LOG.debug({"event": "klines.format_unknown", "symbol": sym})
                continue

            if len(closes) < 50:
                continue

            rsi_val = _rsi(closes, 14)
            ema21 = _ema(closes[-100:], 21)
            ema50 = _ema(closes[-200:], 50)
            close = float(closes[-1])

            atr_pct = _atr_pct_from_raw(raw_rows, 14) if raw_rows else None
            adx_pack = _adx_from_raw(raw_rows, 14) if raw_rows else None
            adx = adx_pack["adx"] if adx_pack else None
            plus_di = adx_pack["plus_di"] if adx_pack else None
            minus_di = adx_pack["minus_di"] if adx_pack else None

            # SIDE בסיסית + אכיפת ADX_MIN:
            side: Optional[str] = None
            if ema21 > ema50 and (rsi_val or 50) >= 48:
                side = "BUY"
            elif ema21 < ema50 and (rsi_val or 50) <= 52:
                side = "SELL"
            if adx is not None and adx < adx_min:
                side = None

            # ===== ניקוד רכיבים =====
            # 1) RSI distance (עד 3.5 נק')
            score_1 = 0.0
            if rsi_val is not None:
                score_1 = min(3.5, abs(rsi_val - 50.0) / 10.0 * 3.5)

            # 2) EMA trend + bonus (עד 2.5 נק')
            score_2_base = 2.0 if side is not None else 0.0
            conf_bonus = 0.0
            if side == "BUY" and rsi_val is not None and rsi_val >= 55 and close > max(ema21, ema50):
                conf_bonus = 0.5 if (plus_di and minus_di and plus_di > minus_di) else 0.3
            elif side == "SELL" and rsi_val is not None and rsi_val <= 45 and close < min(ema21, ema50):
                conf_bonus = 0.5 if (plus_di and minus_di and minus_di > plus_di) else 0.3
            if adx is not None:
                if adx < adx_min:
                    score_2_base *= 0.4
                    conf_bonus = 0.0
                elif adx >= 30:
                    conf_bonus = min(0.5, conf_bonus + 0.1)
            score_2 = min(2.5, score_2_base + conf_bonus)

            # 3) EMA gap pct (עד 4 נק') — אגרסיבי בעומק:
            score_3 = 0.0
            if ema50 > 0:
                ema_gap_pct = abs(ema21 - ema50) / ema50 * 100.0
                score_3 = min(4.0, ema_gap_pct / 1.2)  # 1.2% => נק' אחת
                if adx is not None:
                    if adx < adx_min:
                        score_3 *= 0.6
                    elif adx >= 30:
                        score_3 = min(4.0, score_3 * 1.1)

            # 4) ATR penalty (שלילי עד -3)
            score_4 = 0.0
            if atr_pct is not None:
                if atr_pct > max_atr_pct:
                    score_4 = -min(3.0, (atr_pct - max_atr_pct) * 0.8)
                elif atr_pct < 0.5:
                    score_4 = -0.3

            raw_total = score_1 + score_2 + score_3 + score_4
            score_total = round(max(0.0, min(raw_total, 10.0)), 2)

            note_parts = []
            if rsi_val is not None:
                note_parts.append(f"rsi={rsi_val:.1f}")
            note_parts.append("ema21>ema50" if ema21 > ema50 else ("ema21<ema50" if ema21 < ema50 else "ema21≈ema50"))
            if atr_pct is not None:
                note_parts.append(f"atr%={atr_pct:.2f}")
            if adx is not None:
                note_parts.append(f"adx={adx:.1f}")
            note = " ".join(note_parts)

            out.append({
                "symbol": sym,
                "timeframe": tf,
                "side": side,
                "score_total": score_total,
                "components": [
                    {"id": 1, "name": "rsi_distance", "score": round(score_1, 2)},
                    {"id": 2, "name": "ema_trend",    "score": round(score_2, 2), "extras": {"confirmation_bonus": round(conf_bonus, 2)}},
                    {"id": 3, "name": "ema_gap_pct",  "score": round(score_3, 2)},
                    {"id": 4, "name": "atr_penalty",  "score": round(score_4, 2)},
                ],
                "note": note,
                "details": {
                    "trend": "UP" if ema21 > ema50 else ("DOWN" if ema21 < ema50 else "FLAT"),
                    "rsi": rsi_val, "ema21": ema21, "ema50": ema50, "close": close,
                    "atr_pct": atr_pct, "adx": adx, "plus_di": plus_di, "minus_di": minus_di
                },
            })
        except Exception as e:
            LOG.debug({"event": "klines.symbol_failed", "symbol": sym, "error": str(e)})
            continue

    return out





























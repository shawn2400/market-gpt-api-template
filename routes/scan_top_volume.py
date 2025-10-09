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


# ========= Profile Button (ENV: REGIME_PROFILE) =========
def _apply_profile_overrides() -> None:
    """
    REGIME_PROFILE: AUTO | AGGRESSIVE | BALANCED | CONSERVATIVE
    מחיל override לערכי ENV כך שכל הקוד משתמש בהם מיידית.
    """
    prof = (os.getenv("REGIME_PROFILE", "AUTO") or "AUTO").strip().upper()
    overrides: Dict[str, Any] = {}

    if prof == "AGGRESSIVE":
        overrides.update({
            "AUTO_MIN_SCORE_BASE": "6.6",
            "TUNE_TABLE_MULT_HIGH": "1.30",
            "TUNE_SAFE_FRAC_HIGH": "0.92",
            "RISK_LEV_MAX": "17",
            "RISK_SCORE_TO_EQUITY_PCT": "6.5:0.7,7:1.0,7.5:1.3,8:1.6,8.5:2.0,9:2.4,9.5:3.0",
        })

    elif prof == "CONSERVATIVE":
        overrides.update({
            "ADX_MIN": "27",
            "TUNE_TABLE_MULT_LOW": "0.80",
            "TUNE_SAFE_FRAC_LOW": "0.75",
            "RISK_LEV_MAX": "12",
            "RISK_SCORE_TO_EQUITY_PCT": "6.5:0.5,7:0.8,7.5:1.0,8:1.2,8.5:1.5,9:1.8,9.5:2.2",
        })

    elif prof == "BALANCED":
        overrides.update({
            "AUTO_MIN_SCORE_BASE": "6.9",
            "TUNE_TABLE_MULT_HIGH": "1.22",
            "TUNE_SAFE_FRAC_HIGH": "0.90",
        })

    if overrides:
        for k, v in overrides.items():
            os.environ[k] = str(v)

_apply_profile_overrides()


# ראוטר מוגן (דורש Bearer)
router = APIRouter(prefix="/scan", tags=["scan"], dependencies=[Depends(require_bearer_token)])
# ראוטר ציבורי (לנתיב /scan/public-now)
router_public = APIRouter(prefix="/scan", tags=["scan"])

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

def _get_env_int(key: str, default: int) -> int:
    try:
        return int(float(os.getenv(key, str(default))))
    except Exception:
        return default

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def _parse_score_equity_table(raw: str) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    raw = (raw or "").strip()
    if not raw:
        return out
    for p in raw.split(","):
        p = p.strip()
        if not p or ":" not in p:
            continue
        k, v = p.split(":")
        try:
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

# ============================
# Auto Risk (Leverage + Stake %Equity)
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
    enabled = (os.getenv("AUTO_RISK_ENABLE", "1").strip() == "1")

    lev_base = _get_env_float("RISK_LEV_BASE", default_leverage)
    lev_min  = _get_env_float("RISK_LEV_MIN",  5.0)
    lev_max  = _get_env_float("RISK_LEV_MAX", 15.0)

    equity_base_pct = _get_env_float("RISK_STAKE_EQUITY_BASE_PCT", 1.0)
    equity_min_pct  = _get_env_float("RISK_STAKE_EQUITY_MIN_PCT",  0.3)
    equity_max_pct  = _get_env_float("RISK_STAKE_EQUITY_MAX_PCT",  2.5)

    stake_min_usd = _get_env_float("RISK_STAKE_MIN_USDT", 25.0)
    stake_max_usd = _get_env_float("RISK_STAKE_MAX_USDT", 500.0)

    tbl_raw = os.getenv("RISK_SCORE_TO_EQUITY_PCT", "6.5:0.6,7:0.9,7.5:1.1,8:1.3,8.5:1.7,9:2.0,9.5:2.5")
    score_tbl = _parse_score_equity_table(tbl_raw)

    adx_strong = _get_env_float("RISK_ADX_STRONG", 35.0)
    adx_weak   = _get_env_float("RISK_ADX_WEAK",   20.0)
    atr_hi     = _get_env_float("RISK_ATR_HIGH_PCT", 4.0)
    atr_lo     = _get_env_float("RISK_ATR_LOW_PCT",  0.7)

    stake_boost_strong = _get_env_float("RISK_STAKE_BOOST_STRONG_PCT", 15.0) / 100.0
    stake_cut_high_atr = _get_env_float("RISK_STAKE_CUT_HIGH_ATR_PCT",  20.0) / 100.0
    lev_boost_strong   = _get_env_float("RISK_LEV_BOOST_STRONG_PCT",   10.0) / 100.0
    lev_cut_high_atr   = _get_env_float("RISK_LEV_CUT_HIGH_ATR_PCT",   20.0) / 100.0

    extra_mode   = (os.getenv("RISK_EXTRA_ADD_MODE", "pct") or "pct").lower()
    extra_thresh = _get_env_float("RISK_EXTRA_ADD_THRESH", 9.0)
    extra_value  = _get_env_float("RISK_EXTRA_ADD_VALUE",  25.0)

    if not enabled:
        lev = _clamp(lev_base, lev_min, lev_max)
        stake = _clamp(default_stake_usdt, stake_min_usd, stake_max_usd)
        return round(lev, 2), round(stake, 2)

    lev = lev_base

    if equity_usdt and equity_usdt > 0:
        score = float(score_total or 0.0)
        pct_equity = _score_to_equity_pct(score, score_tbl, equity_base_pct)
        pct_equity = _clamp(pct_equity, equity_min_pct, equity_max_pct)
        stake = equity_usdt * (pct_equity / 100.0)
    else:
        stake = default_stake_usdt

    if adx is not None:
        if adx >= adx_strong:
            lev *= (1.0 + lev_boost_strong)
            stake *= (1.0 + stake_boost_strong)
        elif adx <= adx_weak:
            lev *= 0.9
            stake *= 0.9

    if atr_pct is not None:
        if atr_pct >= atr_hi:
            lev *= (1.0 - lev_cut_high_atr)
            stake *= (1.0 - stake_cut_high_atr)
        elif atr_pct <= atr_lo:
            stake *= 0.95

    if score_total is not None and score_total >= extra_thresh:
        if extra_mode == "pct":
            stake *= (1.0 + (extra_value / 100.0))
        else:
            stake += extra_value

    lev = _clamp(lev, lev_min, lev_max)
    stake = _clamp(stake, stake_min_usd, stake_max_usd)
    return round(lev, 2), round(stake, 2)

# ============================
# Auto TP/SL (ATR + ADX)
# ============================

def _auto_tp_sl(*, side: Optional[str], entry: float, atr_pct: Optional[float], adx: Optional[float]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    if entry <= 0 or atr_pct is None:
        return {"stopPrice": None}, []

    sl_mult = _get_env_float("SL_ATR_MULT_BASE", 1.10)
    tp1_mult = _get_env_float("TP1_ATR_MULT_BASE", 1.20)
    tp2_mult = _get_env_float("TP2_ATR_MULT_BASE", 2.20)
    tp3_mult = _get_env_float("TP3_ATR_MULT_BASE", 3.50)

    adx_boost_thr = _get_env_float("ADX_TP_BOOST_THRESH", 30.0)
    adx_tp_boost_pct = _get_env_float("ADX_TP_BOOST_PCT", 10.0) / 100.0
    adx_sl_tight_pct = _get_env_float("ADX_STRONG_SL_TIGHTEN_PCT", 10.0) / 100.0
    adx_low_sl_relax_pct = _get_env_float("ADX_LOW_SL_RELAX_PCT", 10.0) / 100.0
    adx_low_tp_shrink_pct = _get_env_float("ADX_LOW_TP_SHRINK_PCT", 10.0) / 100.0

    atr_abs = entry * (atr_pct / 100.0)

    def _round_px(x: float) -> float:
        return float(f"{x:.6f}")

    side_up = (side or "").upper()
    if side_up == "BUY":
        sl = _round_px(entry - sl_mult * atr_abs)
        tps = [
            {"pct": None, "price": _round_px(entry + tp1_mult * atr_abs), "split": 0.40},
            {"pct": None, "price": _round_px(entry + tp2_mult * atr_abs), "split": 0.35},
            {"pct": None, "price": _round_px(entry + tp3_mult * atr_abs), "split": 0.25},
        ]
    elif side_up == "SELL":
        sl = _round_px(entry + sl_mult * atr_abs)
        tps = [
            {"pct": None, "price": _round_px(entry - tp1_mult * atr_abs), "split": 0.40},
            {"pct": None, "price": _round_px(entry - tp2_mult * atr_abs), "split": 0.35},
            {"pct": None, "price": _round_px(entry - tp3_mult * atr_abs), "split": 0.25},
        ]
    else:
        return {"stopPrice": None}, []

    # התאמות לפי ADX
    if adx is not None:
        if adx >= adx_boost_thr:
            tps = [{**t, "price": _round_px(entry + (t["price"] - entry) * 1.10 if side_up == "BUY" else entry - (entry - t["price"]) * 1.10)} for t in tps]
            sl = _round_px(entry - (entry - sl) * 0.90 if side_up == "BUY" else entry + (sl - entry) * 0.90)
        elif adx < adx_boost_thr - 10:
            tps = [{**t, "price": _round_px(entry + (t["price"] - entry) * 0.90 if side_up == "BUY" else entry - (entry - t["price"]) * 0.90)} for t in tps]
            sl = _round_px(entry - (entry - sl) * 1.10 if side_up == "BUY" else entry + (sl - entry) * 1.10)

    return {"stopPrice": sl}, tps

# ============================
# Filters / Notify / Heartbeat
# ============================

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

# ============================
# Routes
# ============================

@router.get("/top-volume", summary="Scan (real data only) with post-filter, notify/TTL/heartbeat + AutoRisk/TP + Profile")
async def scan_top_volume(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    min_score: float = Query(0.0),
    require_side: bool = Query(False),
    notify: Optional[str] = Query(None, description="currently supported: 'telegram'"),
    chat_id: Optional[str] = Query(None),
    rich: bool = Query(True),
    ttl_sec: int = Query(900, ge=60, le=86400),
    rearm_score: float = Query(6.0),
    dedupe_window_sec: int = Query(300, ge=0, le=3600),
    leverage: float = Query(float(os.getenv("DEFAULT_LEVERAGE", "10"))),
    stake_usdt: float = Query(float(os.getenv("DEFAULT_STAKE_USDT", "50"))),
):
    if notify not in {"telegram", None}:
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
                    entry_price = float(det.get("close") or 0.0) or 0.0

                    eq_env = os.getenv("ACCOUNT_EQUITY_USDT", "").strip()
                    equity = float(eq_env) if eq_env else None

                    dyn_lev, dyn_stake = _auto_risk(
                        score_total=score_val,
                        adx=adx_val,
                        atr_pct=atr_val,
                        equity_usdt=equity,
                        default_leverage=leverage,
                        default_stake_usdt=stake_usdt,
                    )

                    sl_obj, tp_list = _auto_tp_sl(
                        side=s.get("side"),
                        entry=entry_price,
                        atr_pct=atr_val,
                        adx=adx_val,
                    )

                    plan: Dict[str, Any] = {
                        "symbol": s.get("symbol"),
                        "side": s.get("side"),
                        "score": s.get("score_total"),
                        "timeframe": s.get("timeframe") or timeframe,
                        "order_type": "MARKET",
                        "entry_price": entry_price,
                        "sl": sl_obj,
                        "tp": tp_list,
                        "budget_usd": dyn_stake,
                        "leverage": dyn_lev,
                        "ttl_sec": ttl_sec,
                        "why": s.get("note") or (det.get("trend")) or "—",
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
    symbol: Optional[str] = Query(None),
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

# ===== נתיב ציבורי: /scan/public-now (ללא Bearer) =====
@router_public.get("/public-now", summary="Public alias to /scan/now (no auth)")
async def scan_public_now(
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    interval: str = Query("15m", alias="timeframe"),
    kline_limit: int = Query(200, ge=60, le=1000),
    min_score: float = Query(0.0),
    require_side: bool = Query(False),
    symbols_csv: Optional[str] = Query(None, description="לא בשימוש כאן; רשימת ברירת מחדל מגיעה מ-WATCHLIST"),
):
    # אין Notify כאן (ציבורי)
    return await scan_now(
        market=market,
        quote=quote,
        limit=limit,
        timeframe=interval,
        kline_limit=kline_limit,
        min_score=min_score,
        require_side=require_side,
        notify=None,
        chat_id=None,
        rich=True,
        ttl_sec=900,
        rearm_score=6.0,
        dedupe_window_sec=300,
        leverage=float(os.getenv("DEFAULT_LEVERAGE", "10")),
        stake_usdt=float(os.getenv("DEFAULT_STAKE_USDT", "50")),
        symbol=None,
    )

# -------- מחשב איתותים: אמיתי בלבד (אין fallback דמו) + ADX --------
async def _compute_signals(market: str, quote: str, limit: int, timeframe: str, kline_limit: int) -> List[Dict[str, Any]]:
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
        return (atr / last_close) * 100.0

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

            if hasattr(df, "__getitem__") and "close" in getattr(df, "columns", []):
                closes = [float(x) for x in df["close"]]
                if "high" in df.columns and "low" in df.columns:
                    raw_rows = [[None, None, float(h), float(l), float(c)]
                                for h, l, c in zip(df["high"][-k:], df["low"][-k:], df["close"][-k:])]
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

            side: Optional[str] = None
            if ema21 > ema50 and (rsi_val or 50) >= 48:
                side = "BUY"
            elif ema21 < ema50 and (rsi_val or 50) <= 52:
                side = "SELL"
            if adx is not None and adx < adx_min:
                side = None

            # ===== ניקוד רכיבים =====
            score_1 = 0.0
            if rsi_val is not None:
                score_1 = min(3.5, abs(rsi_val - 50.0) / 10.0 * 3.5)

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

            score_3 = 0.0
            if ema50 > 0:
                ema_gap_pct = abs(ema21 - ema50) / ema50 * 100.0
                score_3 = min(4.0, ema_gap_pct / 1.2)
                if adx is not None:
                    if adx < adx_min:
                        score_3 *= 0.6
                    elif adx >= 30:
                        score_3 = min(4.0, score_3 * 1.1)

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


























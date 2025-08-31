# utils/trade_validator.py
from __future__ import annotations
import os, math, time, json
from typing import Dict, Any, Optional, Tuple, List

# שים לב: כל הייבוא הפנימי עטוף ב-try כדי לא להפיל אם מודול מסוים חסר/משתנה אצלך.
try:
    from utils.get_klines import get_klines
except Exception:  # pragma: no cover
    get_klines = None

try:
    from utils.indicators import compute_indicators as _compute_ind
except Exception:
    _compute_ind = None

try:
    from utils.quality_score import compute_quality_score as _quality
except Exception:
    _quality = None

try:
    from utils.funding_bias import get_funding_rate as _funding
except Exception:
    _funding = None

try:
    from utils.binance_client import futures_exchange_info_safe as _fex
except Exception:
    _fex = None

try:
    from utils.trade_store import list_active as _list_active
except Exception:
    _list_active = None

# --- ENV knobs ---
VALIDATOR_STRICT           = os.getenv("VALIDATOR_STRICT", "1").lower() in ("1","true","yes")
VALIDATOR_BARS_MIN         = int(os.getenv("VALIDATOR_BARS_MIN", "200"))
VALIDATOR_TIMEFRESH_SEC    = int(os.getenv("VALIDATOR_TIMEFRESH_SEC", "180"))
VALIDATOR_ENFORCE_BTC_GATE = os.getenv("VALIDATOR_ENFORCE_BTC_GATE","1").lower() in ("1","true","yes")

MIN_RR_TOP10 = float(os.getenv("MIN_RR_TOP10", "1.6"))
MIN_RR_ALT   = float(os.getenv("MIN_RR_ALT",   "1.9"))
TOP10_SYMBOLS = set([s.strip().upper() for s in os.getenv(
    "TOP10_SYMBOLS",
    "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,TRXUSDT,TONUSDT,LTCUSDT"
).split(",") if s.strip()])

# ATR מטרות מתוך ה-SOP שלך:
ATR_SL_MULT     = float(os.getenv("ATR_SL_MULT", "0.6"))   # SL ≈ 0.6×ATR(5m)
ATR_TP1_MULT    = float(os.getenv("ATR_TP1_MULT","1.8"))   # TP1≈ 1.8×ATR(5m)
ATR_TP2_MULT    = float(os.getenv("ATR_TP2_MULT","3.2"))   # TP2≈ 3.2×ATR(5m)
ATR_TOLERANCE   = float(os.getenv("ATR_TOLERANCE","0.4"))  # ±40% טולרנס סביב המולטים

def _now_ms() -> int:
    return int(time.time() * 1000)

def _side_norm(side: str) -> str:
    s = (side or "").upper()
    if s in ("BUY","LONG"):  return "LONG"
    if s in ("SELL","SHORT"): return "SHORT"
    return s or "LONG"

def _rr(entry: float, sl: float, tp: float, side: str) -> Optional[float]:
    try:
        if side == "LONG":
            risk  = entry - sl
            reward= tp - entry
        else:
            risk  = sl - entry
            reward= entry - tp
        if risk <= 0 or reward <= 0:
            return None
        return reward / risk
    except Exception:
        return None

def _near(val: Optional[float], ref: Optional[float], pct: float=0.35) -> bool:
    if val is None or ref is None: return False
    return abs(val - ref) <= abs(ref) * pct

async def _fetch_df(symbol: str, interval: str, market: str, limit: int=500):
    if not get_klines:
        raise RuntimeError("get_klines missing")
    df = await get_klines(symbol, interval=interval, market=market, limit=limit)
    if df is None or len(df) < VALIDATOR_BARS_MIN:
        raise RuntimeError(f"not_enough_bars({len(df) if df is not None else 0})")
    return df

def _last_ts(df) -> Optional[int]:
    try:
        # get_klines אצלך מחזיר עמודת open_time או close_time במיליס.
        for col in ("close_time","open_time","openTime","closeTime"):
            if col in df.columns:
                return int(df[col].iloc[-1])
    except Exception:
        pass
    return None

def _atr5(df) -> Optional[float]:
    # ננסה למצוא ATR מוכן; אם אין, נחשב ידני בסיסי
    for col in ("atr_5","ATR_5","atr5"):
        if col in df.columns:
            try:
                v = float(df[col].iloc[-1])
                if v == v and v > 0: return v
            except Exception: pass
    # חישוב ידני פשוט אם אין:
    try:
        import numpy as np
        h = df["high"].astype(float).to_numpy()
        l = df["low"].astype(float).to_numpy()
        c = df["close"].astype(float).to_numpy()
        tr = np.zeros_like(c)
        tr[1:] = np.maximum.reduce([
            h[1:] - l[1:],
            np.abs(h[1:] - c[:-1]),
            np.abs(l[1:] - c[:-1])
        ])
        n = 5 if len(tr) >= 5 else len(tr)
        if n <= 1: return None
        return float(np.mean(tr[-n:]))
    except Exception:
        return None

async def _btc_gate_ok(side: str) -> Tuple[bool,str]:
    if not VALIDATOR_ENFORCE_BTC_GATE:
        return True, "btc_gate_disabled"
    try:
        df = await _fetch_df("BTCUSDT", "15m", "futures", limit=200)
        # נעשה EMA21/EMA50 בסיסי; אם יש compute_indicators נשתמש בו.
        ema21 = ema50 = None
        if _compute_ind:
            dfi = await _compute_ind(df) if callable(_compute_ind) else _compute_ind(df)
            for col in ("ema_21","EMA_21","ema21"):
                if col in dfi.columns: ema21 = float(dfi[col].iloc[-1])
            for col in ("ema_50","EMA_50","ema50"):
                if col in dfi.columns: ema50 = float(dfi[col].iloc[-1])
        if ema21 is None or ema50 is None:
            # fallback פשוט
            import pandas as pd
            ema21 = float(pd.Series(df["close"]).ewm(span=21, adjust=False).mean().iloc[-1])
            ema50 = float(pd.Series(df["close"]).ewm(span=50, adjust=False).mean().iloc[-1])
        if ema21 >= ema50 and side == "SHORT":
            return False, "btc_up_long_only"
        if ema21 <= ema50 and side == "LONG":
            return False, "btc_down_short_only"
        return True, "btc_gate_ok"
    except Exception as e:
        # אם לא הצלחנו להביא BTC — לא להפיל; נחזיר אזהרה בלבד
        return True, f"btc_gate_skip:{type(e).__name__}"

async def validate_proposal(
    proposal: Dict[str, Any],
    interval: str = "15m",
    market: str = "futures",
    notional_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """
    proposal keys expected: symbol, side(BUY/SELL/LONG/SHORT), entry, sl, tp1[,tp2,tp3], leverage, current_price?, success_pct?
    """
    out = {"ok": False, "errors": [], "warnings": [], "normalized": {}}
    # --- normalize ---
    sym = (proposal.get("symbol") or "").upper().strip()
    side = _side_norm(proposal.get("side") or "")
    entry = proposal.get("entry"); sl = proposal.get("sl")
    tp1 = proposal.get("tp1"); tp2 = proposal.get("tp2"); tp3 = proposal.get("tp3")

    if not sym:
        out["errors"].append("missing_symbol")
    if side not in ("LONG","SHORT"):
        out["errors"].append("bad_side")
    for k,v in (("entry",entry),("sl",sl),("tp1",tp1)):
        if v is None or not isinstance(v,(int,float)):
            out["errors"].append(f"missing_{k}")

    if out["errors"]:
        return out

    # --- exchange/symbol sanity ---
    if _fex:
        try:
            ex = await _fex()
            syms = {s["symbol"]: s for s in ex.get("symbols", []) if s.get("status") == "TRADING"}
            if sym not in syms:
                out["errors"].append("symbol_not_listed_or_not_trading")
                return out
            # אפשר להקשיח רק PERPETUAL אם תרצה: if syms[sym].get("contractType")!="PERPETUAL": ...
        except Exception:
            out["warnings"].append("exchange_info_unavailable")

    # --- price-side consistency ---
    try:
        if side == "LONG":
            if not (entry > sl): out["errors"].append("long_sl_must_be_below_entry")
            if tp1 is not None and not (tp1 > entry): out["errors"].append("long_tp1_must_be_above_entry")
            if tp2 is not None and not (tp2 > entry): out["warnings"].append("long_tp2_nonpositive")
            if tp3 is not None and not (tp3 > entry): out["warnings"].append("long_tp3_nonpositive")
        else:
            if not (entry < sl): out["errors"].append("short_sl_must_be_above_entry")
            if tp1 is not None and not (tp1 < entry): out["errors"].append("short_tp1_must_be_below_entry")
            if tp2 is not None and not (tp2 < entry): out["warnings"].append("short_tp2_nonpositive")
            if tp3 is not None and not (tp3 < entry): out["warnings"].append("short_tp3_nonpositive")
    except Exception:
        out["errors"].append("price_relation_error")

    if out["errors"]:
        return out

    # --- fetch data & indicators (for ATR/RR/quality) ---
    try:
        df = await _fetch_df(sym, interval, market, limit=max(VALIDATOR_BARS_MIN, 300))
    except Exception as e:
        out["errors"].append(f"klines_error:{type(e).__name__}")
        return out

    last_ts = _last_ts(df)
    if last_ts:
        if (_now_ms() - last_ts) > VALIDATOR_TIMEFRESH_SEC * 1000:
            out["warnings"].append("data_stale")

    # compute indicators if available
    if _compute_ind:
        try:
            dfi = await _compute_ind(df) if callable(_compute_ind) else _compute_ind(df)
        except Exception:
            dfi = df
            out["warnings"].append("indicators_failed")
    else:
        dfi = df

    # --- ATR sanity vs SOP ---
    atr = _atr5(dfi)
    if atr is None or not math.isfinite(atr) or atr <= 0:
        out["warnings"].append("atr_missing")
    else:
        try:
            if side == "LONG":
                sl_dist = entry - sl
                tp1_dist= tp1 - entry if tp1 is not None else None
            else:
                sl_dist = sl - entry
                tp1_dist= entry - tp1 if tp1 is not None else None

            # SL≈0.6×ATR, TP1≈1.8×ATR (טולרנס ±ATR_TOLERANCE)
            def _within(x, target, tol):
                return (x is not None) and (abs(x - target) <= target * tol)

            sl_target = ATR_SL_MULT * atr
            if not _within(sl_dist, sl_target, ATR_TOLERANCE):
                out["warnings"].append(f"sl_vs_atr_off: got={sl_dist:.6f} target≈{sl_target:.6f}")

            if tp1 is not None:
                tp1_target = ATR_TP1_MULT * atr
                if not _within(tp1_dist, tp1_target, ATR_TOLERANCE):
                    out["warnings"].append(f"tp1_vs_atr_off: got={tp1_dist:.6f} target≈{tp1_target:.6f}")
        except Exception:
            out["warnings"].append("atr_check_failed")

    # --- RR thresholds (Top10 מול Alt) ---
    rr1 = _rr(entry, sl, tp1, side) if tp1 is not None else None
    if rr1 is None:
        out["errors"].append("rr1_invalid")
        return out
    min_rr = MIN_RR_TOP10 if sym in TOP10_SYMBOLS else MIN_RR_ALT
    if rr1 < min_rr:
        msg = f"rr1_below_min:{rr1:.2f}<{min_rr:.2f}"
        if VALIDATOR_STRICT:
            out["errors"].append(msg)
        else:
            out["warnings"].append(msg)

    # --- Quality score (אם קיים) ---
    if _quality:
        try:
            q = float(_quality(dfi))
            out["normalized"]["quality"] = q
        except Exception:
            out["warnings"].append("quality_failed")

    # --- BTC-Gate ---
    ok_btc, reason = await _btc_gate_ok(side)
    if not ok_btc:
        if sym in ("BTCUSDT","BTCUSD_PERP"):  # אפשר להחריג BTC עצמו
            out["warnings"].append(f"btc_gate_ignored_for_btc:{reason}")
        else:
            if VALIDATOR_STRICT:
                out["errors"].append(f"btc_gate_block:{reason}")
            else:
                out["warnings"].append(f"btc_gate_warn:{reason}")

    # --- Funding bias (רק אזהרה) ---
    if _funding:
        try:
            fr = float(_funding(sym) or 0.0)
            # אם מובהק נגד הכיוון — אזהרה
            if (side == "LONG" and fr > 0.0003) or (side == "SHORT" and fr < -0.0003):
                out["warnings"].append(f"funding_bias:{fr:.6f}")
        except Exception:
            out["warnings"].append("funding_unavailable")

    # --- De-dup (אין טרייד פעיל זהה) ---
    if _list_active:
        try:
            items = _list_active()
            for it in items:
                if str(it.get("symbol","")).upper() == sym and _side_norm(it.get("side","")) == side:
                    out["warnings"].append("duplicate_active_trade_same_symbol_side")
                    if VALIDATOR_STRICT:
                        out["errors"].append("duplicate_active_block")
                        break
        except Exception:
            out["warnings"].append("dedup_check_failed")

    # --- Done ---
    out["normalized"].update({
        "symbol": sym, "side": side, "entry": float(entry), "sl": float(sl),
        "tp1": float(tp1) if tp1 is not None else None,
        "tp2": float(tp2) if tp2 is not None else None,
        "tp3": float(tp3) if tp3 is not None else None,
        "rr1": rr1,
        "interval": interval, "market": market,
        "atr5": float(atr) if atr else None,
    })

    out["ok"] = (len(out["errors"]) == 0)
    return out

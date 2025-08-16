# utils/multi_tf_scanner.py
from __future__ import annotations

import logging
import asyncio
from typing import Sequence, List, Dict, Optional, Any, Tuple

from utils import config
from utils.watchlist_utils import load_watchlist
from utils.trending_utils import get_trending_symbols
from utils.scanner_utils import analyze_symbol, fetch_ohlcv
from utils.ai_analysis import analyze_with_ai
from utils.indicators import compute_indicators
from utils.btc_anchor import compute_btc_anchor

# גבולות/דיפולטים
MAX_SYMBOLS = max(1, min(int(getattr(config, "TOP_SYMBOLS", 30)), 50))
FALLBACK_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
BTC_REF_TF = "15m"

# ----------------- עזרים -----------------
def _normalize_direction(val: Any) -> str:
    d = str(val or "").strip().upper()
    if d in ("LONG", "BUY"):
        return "LONG"
    if d in ("SHORT", "SELL"):
        return "SHORT"
    return "LONG"

def _dedup_upper(seq: Sequence[str]) -> List[str]:
    seen, out = set(), []
    for s in seq or []:
        u = str(s).upper()
        if u and u not in seen:
            seen.add(u); out.append(u)
    return out

def _symbols_from_watchlist(min_quality: float) -> List[str]:
    try:
        wl = load_watchlist(min_quality=min_quality) or []
        syms = [str(item.get("symbol", "")) for item in wl if isinstance(item, dict)]
        return _dedup_upper(syms)
    except Exception as e:
        logging.warning(f"[multi_tf_scanner] watchlist load failed: {e}")
        return []

async def _safe_analyze(symbol: str, tf: str, market: str, trending_only: bool) -> Optional[Dict]:
    try:
        return await analyze_symbol(
            symbol=symbol,
            market_type=market,
            interval=tf,
            limit=150,
            trending_only=trending_only,  # תאימות
            with_ai=False,                # AI בשכבה העליונה
            frames=[tf],
        )
    except Exception as e:
        logging.error(f"[multi_tf_scanner] analyze_symbol failed for {symbol}@{tf}: {e}", exc_info=True)
        return None

async def _get_btc_direction() -> Optional[str]:
    """
    מגמת BTC לפי EMA21/EMA50 על 15m (fallback מהיר במקרה שאין btc_anchor).
    """
    try:
        df = await fetch_ohlcv("BTCUSDT", interval=BTC_REF_TF, limit=120)
        if df is None or df.empty:
            return None
        df_ind = compute_indicators(df)
        if df_ind is None or df_ind.empty:
            return None
        last_row = df_ind.iloc[-1]
        ema_21 = float(last_row.get("ema_21"))
        ema_50 = float(last_row.get("ema_50"))
        if ema_21 > ema_50:
            return "LONG"
        if ema_21 < ema_50:
            return "SHORT"
        return None
    except Exception as e:
        logging.warning(f"[btc_correlation] failed to get BTC trend: {e}")
        return None

def _aggregate_metrics(frames: List[Dict]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    if not frames:
        return None, None, None, None
    best = max(frames, key=lambda d: float(d.get("quality_score", 0.0)))
    last = frames[-1]

    def pick(key: str):
        return best.get(key) if best.get(key) not in (None, "") else last.get(key)

    entry = pick("close")
    atr   = pick("atr")
    rsi   = pick("rsi")
    adx   = pick("adx")
    try:
        entry = float(entry) if entry is not None else None
    except Exception:
        entry = None
    try:
        atr = float(atr) if atr is not None else None
    except Exception:
        atr = None
    try:
        rsi = float(rsi) if rsi is not None else None
    except Exception:
        rsi = None
    try:
        adx = float(adx) if adx is not None else None
    except Exception:
        adx = None
    return entry, atr, rsi, adx

def _auto_leverage(atrp: Optional[float], adx: Optional[float], quality: float, btc_strength: Optional[float]) -> int:
    """
    חישוב מינוף אוטומטי 5×–35×:
    - בסיס לפי איכות (6→10×, 10→24×).
    - ADX מחזק עד +6×.
    - ATR% מפחית עד −10×.
    - חוזק עוגן BTC מחזק עד +5×.
    """
    q = float(quality)
    base = 10.0 + max(0.0, min(14.0, (q - 6.0) * 3.5))  # 6→10, 10→24
    boost = 0.0
    if adx is not None:
        boost += max(0.0, min(6.0, (float(adx) - 20.0) * 0.3))
    if btc_strength is not None:
        boost += max(0.0, min(5.0, (float(btc_strength) - 55.0) * 0.15))
    penalty = 0.0
    if atrp is not None:
        # ATR% גבוה → להוריד מינוף
        if atrp >= 2.0:
            penalty = 10.0
        elif atrp >= 1.2:
            penalty = 6.0
        elif atrp >= 0.8:
            penalty = 3.0
    lev = base + boost - penalty
    return int(max(5.0, min(35.0, round(lev))))

def _make_fast_reply(decision_yes: bool, direction: str, entry: Optional[float], atr: Optional[float], lev: int) -> str:
    """
    SOP “קצר”: החלטה | כיוון | כניסה | SL | TP1/TP2 | $40@×LEV | BTC Gate
    SL = 0.6×ATR ; TP1=1.8×ATR ; TP2=3.2×ATR
    """
    try:
        d = "כן" if decision_yes else "לא"
        dir_ = "LONG" if direction == "LONG" else "SHORT"
        if entry is None or atr is None:
            return f"{d} | {dir_} | — | SL — | TP1/TP2 — | $40@×{lev} | BTC Gate"
        sl   = entry - 0.6*atr if dir_ == "LONG" else entry + 0.6*atr
        tp1  = entry + 1.8*atr if dir_ == "LONG" else entry - 1.8*atr
        tp2  = entry + 3.2*atr if dir_ == "LONG" else entry - 3.2*atr
        def fmt(x: float) -> str:
            return f"{x:.6f}".rstrip("0").rstrip(".")
        return f"{d} | {dir_} | {fmt(entry)} | SL {fmt(sl)} | TP1 {fmt(tp1)}/TP2 {fmt(tp2)} | $40@×{lev} | BTC Gate"
    except Exception:
        return f"{'כן' if decision_yes else 'לא'} | {direction} | — | SL — | TP1/TP2 — | $40@×{lev} | BTC Gate"

async def _build_symbol_list(
    symbols: Optional[Sequence[str]],
    min_quality: float,
    trending_only: bool,
    trending_source: str,
    market: str,
) -> List[str]:
    try:
        if symbols:
            syms = [str(s).strip().upper() for s in symbols if s]
        else:
            syms = _symbols_from_watchlist(min_quality)
        if trending_only or not syms:
            try:
                trending = get_trending_symbols(trending_source, market) or []
                trending = [str(s).strip().upper() for s in trending if s]
                if syms and trending_only:
                    syms = [s for s in syms if s in set(trending)]
                if not syms:
                    syms = trending
            except Exception as e:
                logging.warning(f"[multi_tf_scanner] Trending fetch error: {e}")
        if not syms:
            syms = FALLBACK_SYMBOLS
        return _dedup_upper(syms)[:MAX_SYMBOLS]
    except Exception as e:
        logging.error(f"[multi_tf_scanner] Symbol list build failed: {e}", exc_info=True)
        return FALLBACK_SYMBOLS

# ----------------- הסורק הראשי -----------------
async def multi_tf_scan_with_ai(
    timeframes: Sequence[str] = ("5m", "15m", "1h"),
    markets: Sequence[str] = ("futures",),
    min_quality: float = 6,
    top: int = 10,
    trending_only: bool = False,
    trending_source: str = "coingecko",
    symbols: Optional[Sequence[str]] = None,
    *,
    hard_btc_filter: bool = False,
    allow_divergence: bool = False,  # preview בלבד
) -> List[Dict]:
    raw_tfs = timeframes or ("15m", "1h")
    tfs = tuple([s for s in (str(x).strip() for x in raw_tfs) if s])

    market = str((markets[0] if markets else "futures")).lower()
    top_n = max(1, int(top))

    syms = await _build_symbol_list(symbols, min_quality, trending_only, trending_source, market)
    if not syms:
        return []

    # ניתוח לכל סימבול/טיימפריים (מקבילי)
    tasks = [_safe_analyze(sym, tf, market, trending_only) for sym in syms for tf in tfs]
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

    frames: List[Dict] = []
    for r in results_raw:
        if isinstance(r, dict) and r.get("symbol"):
            frames.append(r)

    if not frames:
        return []

    # קיבוץ לפי סימבול
    grouped: Dict[str, List[Dict]] = {}
    for r in frames:
        sym = str(r.get("symbol")).upper()
        grouped.setdefault(sym, []).append(r)

    # BTC Anchor (כיוון+עוצמה)
    anchor = await compute_btc_anchor(frames=("15m",), market=market)
    btc_dir = anchor.get("direction") or await _get_btc_direction()
    btc_strength = float(anchor.get("strength", 0.0) or 0.0)
    logging.info(f"[btc_anchor] dir={btc_dir} strength={btc_strength} on {BTC_REF_TF}")

    final: List[Dict] = []
    for sym, data in grouped.items():
        avg_q = sum(float(d.get("quality_score", 0)) for d in data) / max(1, len(data))
        if avg_q < float(min_quality):
            continue

        # נרמול כיוונים
        for d in data:
            d["direction"] = _normalize_direction(d.get("direction") or d.get("main_direction"))

        # החלטת AI (עם פולבק בטוח)
        try:
            ai = await analyze_with_ai(data)
        except Exception as e:
            logging.warning(f"[multi_tf_scanner] AI failed for {sym}: {e}")
            ai = {}

        def _fallback():
            d = _normalize_direction(data[-1].get("direction"))
            return {
                "symbol": sym,
                "direction": d,
                "signal": "BUY" if d == "LONG" else "SELL",
                "quality_score": round(avg_q, 2),
                "confidence": 50.0,
                "frames": [f.get("interval") for f in data],
                "details": data,
            }

        out = dict(ai) if isinstance(ai, dict) and ai else _fallback()
        out["symbol"] = sym
        out["direction"] = _normalize_direction(out.get("direction"))
        out["signal"] = (out.get("signal") or "HOLD").upper()
        out["quality_score"] = float(out.get("quality_score", avg_q))
        out["frames"] = out.get("frames") or [f.get("interval") for f in data]
        out["details"] = out.get("details") or data

        # הזרקת מדדים עליונים (entry/atr/rsi/adx) ברמת הפריט
        entry, atr, rsi, adx = _aggregate_metrics(data)
        if entry is not None:
            out["entry"] = entry
        if atr is not None:
            out["atr"] = atr
        if rsi is not None:
            out["rsi"] = rsi
        if adx is not None:
            out["adx"] = adx

        # חישוב ATR% לצורך מינוף
        atrp = (atr / entry * 100.0) if (atr is not None and entry) else None
        lev = _auto_leverage(atrp, adx, out["quality_score"], btc_strength)
        out["leverage_suggest"] = lev

        # --- Hard Preview: יישור ל-BTC + שדות עזר ---
        aligned = (btc_dir is not None and out["direction"] == btc_dir)
        out["btc_dir"] = btc_dir
        out["btc_strength"] = btc_strength
        out["aligned"] = bool(aligned)
        if btc_dir is None:
            out["signal_type"] = "UNKNOWN"
            out["hard_status"] = "FAIL"
            out["hard_reason"] = "BTC neutral/unknown"
            out["executable"] = False
        else:
            if aligned:
                out["signal_type"] = "ALIGNED"
                out["hard_status"] = "PASS"
                out["hard_reason"] = f"Aligned with BTC ({btc_dir}, strength={btc_strength})"
                out["executable"] = True
            else:
                out["signal_type"] = "DIVERGENCE"
                if allow_divergence:
                    out["hard_status"] = "FAIL"
                    out["hard_reason"] = "Against BTC (divergence preview only)"
                    out["executable"] = False
                else:
                    out["hard_status"] = "FAIL"
                    out["hard_reason"] = "BTC-Gate fail"
                    out["executable"] = False

        # fast_reply לפי SOP “קצר”
        out["fast_reply"] = _make_fast_reply(out.get("executable", False), out["direction"], entry, atr, lev)

        final.append(out)

    # --- סינון לפי BTC: Soft/Hard ---
    if btc_dir:
        if hard_btc_filter:
            final = [o for o in final if o.get("aligned")]
        else:
            aligned = [o for o in final if o.get("aligned")]
            if aligned:
                final = aligned

    final.sort(key=lambda x: float(x.get("quality_score", 0)), reverse=True)
    return final[:top_n]

# -------- fallback ידני לסריקה נקודתית --------
async def fallback_scan_manual(symbol: str) -> List[Dict[str, Any]]:
    try:
        symbol = str(symbol or "BTCUSDT").upper()
        tfs = ("15m", "1h")
        market = "futures"
        frames: List[Dict] = []
        for tf in tfs:
            r = await _safe_analyze(symbol, tf, market, trending_only=False)
            if isinstance(r, dict):
                frames.append(r)
        if not frames:
            return []
        avg_q = sum(float(d.get("quality_score", 0)) for d in frames) / max(1, len(frames))
        dir_ = _normalize_direction(frames[-1].get("direction"))
        entry, atr, rsi, adx = _aggregate_metrics(frames)
        anchor = await compute_btc_anchor(frames=("15m",), market=market)
        btc_dir = anchor.get("direction")
        btc_strength = float(anchor.get("strength", 0.0) or 0.0)
        atrp = (atr / entry * 100.0) if (atr is not None and entry) else None
        lev = _auto_leverage(atrp, adx, avg_q, btc_strength)
        out = {
            "symbol": symbol,
            "direction": dir_,
            "signal": "BUY" if dir_ == "LONG" else "SELL",
            "quality_score": round(avg_q, 2),
            "confidence": 50,
            "frames": [f.get("interval") for f in frames],
            "details": frames,
            "entry": entry,
            "atr": atr,
            "rsi": rsi,
            "adx": adx,
            "btc_dir": btc_dir,
            "btc_strength": btc_strength,
            "aligned": (btc_dir is not None and dir_ == btc_dir),
            "hard_status": "FAIL",
            "hard_reason": "fallback only",
            "executable": False,
            "leverage_suggest": lev,
            "fast_reply": _make_fast_reply(False, dir_, entry, atr, lev),
        }
        return [out]
    except Exception as e:
        logging.warning(f"[fallback_scan_manual] failed for {symbol}: {e}")
        return []
























































































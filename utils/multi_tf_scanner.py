# === הוספת התאמה ל־BTC ב־multi_tf_scanner.py ===

import logging
import asyncio
from typing import Sequence, List, Dict, Optional, Any

from utils import config
from utils.watchlist_utils import load_watchlist
from utils.trending_utils import get_trending_symbols
from utils.scanner_utils import analyze_symbol, fetch_ohlcv
from utils.ai_analysis import analyze_with_ai
from utils.indicators import compute_indicators

# הגדרות
MAX_SYMBOLS = max(1, min(int(getattr(config, "TOP_SYMBOLS", 30)), 50))
FALLBACK_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
BTC_REF_TF = "15m"  # טיימפריים לבדיקת מגמה

def _normalize_direction(val: Any) -> str:
    d = str(val or "").strip().upper()
    if d in ("LONG", "BUY"): return "LONG"
    if d in ("SHORT", "SELL"): return "SHORT"
    return "LONG"

def _dedup_upper(seq: Sequence[str]) -> List[str]:
    seen = set(); out: List[str] = []
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
        return await analyze_symbol(symbol=symbol, market_type=market, interval=tf, limit=150, trending_only=trending_only, with_ai=False, frames=[tf])
    except Exception as e:
        logging.error(f"[multi_tf_scanner] analyze_symbol failed for {symbol}@{tf}: {e}", exc_info=True)
        return None

async def _get_btc_direction() -> Optional[str]:
    try:
        df = await fetch_ohlcv("BTCUSDT", interval=BTC_REF_TF, limit=100)
        if df is None or df.empty:
            return None
        df_ind = compute_indicators(df)
        if df_ind.empty:
            return None
        last_row = df_ind.iloc[-1]
        ema_21, ema_50 = last_row["ema_21"], last_row["ema_50"]
        if ema_21 > ema_50:
            return "LONG"
        elif ema_21 < ema_50:
            return "SHORT"
        return None
    except Exception as e:
        logging.warning(f"[btc_correlation] failed to get BTC trend: {e}")
        return None

async def _build_symbol_list(symbols: Optional[Sequence[str]], min_quality: float, trending_only: bool, trending_source: str, market: str) -> List[str]:
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

async def multi_tf_scan_with_ai(
    timeframes: Sequence[str] = ("5m", "15m", "1h"),
    markets: Sequence[str] = ("futures",),
    min_quality: float = 6,
    top: int = 10,
    trending_only: bool = False,
    trending_source: str = "coingecko",
    symbols: Optional[Sequence[str]] = None,
) -> List[Dict]:
    tfs = tuple([str(x).strip() for x in timeframes or ("15m", "1h")])
    market = str((markets[0] if markets else "futures")).lower()
    top_n = max(1, int(top))

    syms = await _build_symbol_list(symbols, min_quality, trending_only, trending_source, market)
    if not syms:
        return []

    tasks = [_safe_analyze(sym, tf, market, trending_only) for sym in syms for tf in tfs]
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

    frames: List[Dict] = []
    for r in results_raw:
        if isinstance(r, dict) and r.get("symbol"):
            frames.append(r)

    grouped: Dict[str, List[Dict]] = {}
    for r in frames:
        sym = str(r.get("symbol")).upper()
        grouped.setdefault(sym, []).append(r)

    btc_dir = await _get_btc_direction()
    logging.info(f"[btc_correlation] BTC trend (via EMA21/50 on {BTC_REF_TF}): {btc_dir}")

    final: List[Dict] = []
    for sym, data in grouped.items():
        avg_q = sum(float(d.get("quality_score", 0)) for d in data) / len(data)
        if avg_q < float(min_quality):
            continue

        for d in data:
            d["direction"] = _normalize_direction(d.get("direction") or d.get("main_direction"))

        ai = await analyze_with_ai(data)

        def _fallback():
            d = _normalize_direction(data[-1].get("direction"))
            return {
                "symbol": sym, "direction": d,
                "signal": "BUY" if d == "LONG" else "SELL",
                "quality_score": round(avg_q, 2),
                "confidence": 50.0, "frames": [f["interval"] for f in data], "details": data,
            }

        out = dict(ai) if isinstance(ai, dict) else _fallback()
        out["symbol"] = sym
        out["direction"] = _normalize_direction(out.get("direction"))
        out["signal"] = out.get("signal", "HOLD").upper()
        out["quality_score"] = float(out.get("quality_score", avg_q))
        out["frames"] = out.get("frames") or [f["interval"] for f in data]
        out["details"] = out.get("details") or data

        # --- התאמה למגמת BTC ---
        if btc_dir and out["direction"] != btc_dir:
            logging.info(f"[btc_correlation] FILTERED {sym}: direction={out['direction']} BTC={btc_dir}")
            continue

        final.append(out)

    final.sort(key=lambda x: float(x.get("quality_score", 0)), reverse=True)
    return final[:top_n]

















































































# utils/multi_tf_scanner.py
import logging
import asyncio
from typing import Sequence, List, Dict, Optional

from utils.trending_utils import get_trending_symbols
from utils.watchlist_utils import get_symbols_list
from utils.scanner_utils import analyze_symbol  # שים לב: אין יבוא של semaphore כאן
from utils.ai_analysis import analyze_with_ai

MAX_SYMBOLS = 20
FALLBACK_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

async def safe_analyze(symbol: str, tf: str, market: str, trending_only: bool):
    """עטיפת בטיחות: analyze_symbol כבר מגביל מקביליות בפנים (Semaphore/Timeout)."""
    try:
        return await analyze_symbol(
            symbol=symbol,
            market_type=market,
            interval=tf,
            limit=150,
            trending_only=trending_only,
            with_ai=False,
            frames=[tf]
        )
    except Exception as e:
        logging.error(f"[multi_tf_scanner] analyze_symbol failed for {symbol}@{tf}: {e}", exc_info=True)
        return None

async def multi_tf_scan_with_ai(
    timeframes: Sequence[str] = ("5m", "15m", "1h"),
    markets: Sequence[str] = ("futures",),
    min_quality: float = 6,
    top: int = 10,
    trending_only: bool = False,
    trending_source: str = "coingecko",
    symbols: Optional[Sequence[str]] = None
) -> List[Dict]:
    logging.info(f"[multi_tf_scanner] Starting scan: tf={timeframes}, markets={markets}, "
                 f"min_quality={min_quality}, top={top}, trending_only={trending_only}")

    # 1) בניית רשימת סמלים
    syms: List[str] = []
    if symbols:
        syms = [str(s).strip().upper() for s in symbols if s]
    else:
        syms = get_symbols_list(min_quality=min_quality)  # מנרמל ומסנן

    if trending_only or not syms:
        try:
            trending = get_trending_symbols(trending_source, markets[0])
            trending = [str(s).strip().upper() for s in (trending or []) if s]
            if syms:
                keep = set(trending)
                syms = [s for s in syms if s in keep]
            else:
                syms = trending
            logging.info(f"[multi_tf_scanner] Trending symbols: {syms[:MAX_SYMBOLS]}")
        except Exception as e:
            logging.warning(f"[multi_tf_scanner] Trending fetch error: {e}")

    if not syms:
        syms = FALLBACK_SYMBOLS
        logging.warning(f"[multi_tf_scanner] Using fallback symbols: {syms}")

    syms = syms[:MAX_SYMBOLS]

    # 2) הרצת ניתוח לכל TF ולכל סימבול
    tasks = [safe_analyze(sym, tf, markets[0], trending_only) for sym in syms for tf in timeframes]
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

    # 3) ניפוי חריגות ותוצאות לא חוקיות
    frames: List[Dict] = []
    for r in results_raw:
        if isinstance(r, Exception):
            logging.error(f"[multi_tf_scanner] analyze task exception: {r}", exc_info=True)
            continue
        if r and isinstance(r, dict) and r.get("symbol"):
            frames.append(r)

    if not frames:
        logging.info("[multi_tf_scanner] No frame results.")
        return []

    # 4) קיבוץ לפי סימבול
    grouped: Dict[str, List[Dict]] = {}
    for r in frames:
        sym = str(r.get("symbol")).upper()
        grouped.setdefault(sym, []).append(r)

    # 5) סיכום + AI לכל סימבול
    final: List[Dict] = []
    for sym, data in grouped.items():
        avg_q = sum(float(d.get("quality_score", 0) or 0) for d in data) / max(1, len(data))
        if avg_q < float(min_quality):
            continue

        ai = await analyze_with_ai(data)

        def _fallback():
            direction = str((data[-1].get("direction") or "LONG")).upper()
            direction = direction if direction in ("LONG", "SHORT") else "LONG"
            return {
                "symbol": sym,
                "direction": direction,
                "quality_score": round(avg_q, 2),
                "signal": "BUY" if direction == "LONG" else "SELL",
                "confidence": 50.0,
                "frames": [d.get("interval") for d in data],
                "details": data
            }

        if not isinstance(ai, dict) or ai.get("error"):
            logging.warning(f"[multi_tf_scanner] AI unavailable/invalid for {sym}: {ai}")
            final.append(_fallback())
            continue

        # נרמול מפתחות
        out = dict(ai)
        out["symbol"] = sym
        out["direction"] = str(out.get("direction") or "LONG").upper()
        if out["direction"] not in ("LONG", "SHORT"):
            out["direction"] = "LONG"
        sig = str(out.get("signal", "HOLD")).upper()
        out["signal"] = sig if sig in ("BUY", "SELL", "HOLD") else "HOLD"
        out["quality_score"] = float(out.get("quality_score", avg_q) or avg_q)
        out["frames"] = out.get("frames") or [d.get("interval") for d in data]
        out["details"] = out.get("details") or data

        final.append(out)

    final.sort(key=lambda x: float(x.get("quality_score", 0) or 0), reverse=True)
    return final[:top]












































































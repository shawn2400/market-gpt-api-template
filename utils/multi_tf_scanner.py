# utils/multi_tf_scanner.py
import logging
import asyncio
from typing import Sequence, List, Dict, Optional, Any

from utils import config
from utils.watchlist_utils import load_watchlist
from utils.trending_utils import get_trending_symbols
from utils.scanner_utils import analyze_symbol  # שים/י לב: לא מייבאים semaphore כאן!
from utils.ai_analysis import analyze_with_ai

# מגבלת סמלים לסריקה: ניקח את הקטן מבין TOP_SYMBOLS והקשיח 50
MAX_SYMBOLS = max(1, min(int(getattr(config, "TOP_SYMBOLS", 30)), 50))
FALLBACK_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


def _normalize_direction(val: Any) -> str:
    d = str(val or "").strip().upper()
    if d in ("LONG", "BUY"):
        return "LONG"
    if d in ("SHORT", "SELL"):
        return "SHORT"
    return "LONG"


def _dedup_upper(seq: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for s in seq:
        u = str(s).upper()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _symbols_from_watchlist(min_quality: float) -> List[str]:
    try:
        wl = load_watchlist(min_quality=min_quality) or []
        syms = []
        for item in wl:
            if isinstance(item, dict):
                sym = str(item.get("symbol", "")).strip().upper()
                if sym:
                    syms.append(sym)
        return _dedup_upper(syms)
    except Exception as e:
        logging.warning(f"[multi_tf_scanner] watchlist load failed: {e}")
        return []


async def _safe_analyze(symbol: str, tf: str, market: str, trending_only: bool) -> Optional[Dict]:
    """
    עטיפה בטוחה ל-analyze_symbol.
    analyze_symbol עצמו כבר משתמש בסמפור גלובלי – אין צורך להכפיל סמפור כאן.
    """
    try:
        return await analyze_symbol(
            symbol=symbol,
            market_type=market,
            interval=tf,
            limit=150,
            trending_only=trending_only,
            with_ai=False,
            frames=[tf],
        )
    except Exception as e:
        logging.error(f"[multi_tf_scanner] analyze_symbol failed for {symbol}@{tf}: {e}", exc_info=True)
        return None


async def _build_symbol_list(
    symbols: Optional[Sequence[str]],
    min_quality: float,
    trending_only: bool,
    trending_source: str,
    market: str,
) -> List[str]:
    """
    בונה את רשימת הסמלים לסריקה לפי:
    1) symbols שהועברו מבחוץ (executor)
    2) watchlist.json (מסונן לפי min_quality)
    3) trending (אם התבקש או אם אין סמלים)
    4) FALLBACK_SYMBOLS
    """
    try:
        if symbols:
            syms = [str(s).strip().upper() for s in symbols if s]
        else:
            syms = _symbols_from_watchlist(min_quality=min_quality)

        if trending_only or not syms:
            try:
                trending = get_trending_symbols(trending_source, market) or []
                trending = [str(s).strip().upper() for s in trending if s]

                if syms:
                    if trending_only:
                        tset = set(trending)
                        syms = [s for s in syms if s in tset]
                if not syms:
                    syms = trending

                logging.info(f"[multi_tf_scanner] Trending symbols ({trending_source}/{market}): {syms[:MAX_SYMBOLS]}")
            except Exception as e:
                logging.warning(f"[multi_tf_scanner] Trending fetch error: {e}")

        if not syms:
            syms = FALLBACK_SYMBOLS
            logging.warning(f"[multi_tf_scanner] Using fallback symbols: {syms}")

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
    """
    סורק סמלים במספר טיים-פריימים, מסכם לפי ממוצע quality_score, ואז מעביר לאנליזה של AI.
    מחזיר רשימת dict ממוינת לפי quality_score (יורד), עד top תוצאות.
    פלט מובטח לכל פריט: {symbol, direction, quality_score, signal, confidence, frames, details, raw?}
    """
    tfs = tuple([str(x).strip() for x in (timeframes or ("15m", "1h")) if str(x).strip()]) or ("15m", "1h")
    market = str(markets[0] if markets else "futures").lower()
    top_n = max(1, int(top or 10))

    logging.info(
        f"[multi_tf_scanner] Starting scan: tf={tfs}, markets={markets}, "
        f"min_quality={min_quality}, top={top_n}, trending_only={trending_only}"
    )

    # 1) סמלים
    syms = await _build_symbol_list(
        symbols=symbols,
        min_quality=min_quality,
        trending_only=trending_only,
        trending_source=trending_source,
        market=market,
    )
    if not syms:
        logging.info("[multi_tf_scanner] No symbols to scan.")
        return []

    # 2) ניתוח לכל TF ולכל סימבול
    tasks = [_safe_analyze(sym, tf, market, trending_only) for sym in syms for tf in tfs]
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

        # ודאות כיוון
        for d in data:
            d["direction"] = _normalize_direction(d.get("direction") or d.get("main_direction"))

        ai = await analyze_with_ai(data)

        def _fallback() -> Dict:
            direction = _normalize_direction(data[-1].get("direction"))
            return {
                "symbol": sym,
                "direction": direction,
                "quality_score": round(avg_q, 2),
                "signal": "BUY" if direction == "LONG" else "SELL",
                "confidence": 50.0,
                "frames": [d.get("interval") for d in data],
                "details": data,
            }

        # ולידציה של תוצאת ה-AI והשלמת שדות
        if not isinstance(ai, dict):
            logging.warning(f"[multi_tf_scanner] AI analysis result not dict for {sym}: {ai}")
            final.append(_fallback()); continue

        if ai.get("error"):
            logging.warning(f"[multi_tf_scanner] AI analysis error for {sym}: {ai.get('error')}")
            out = _fallback()
            out["error"] = ai.get("error")
            final.append(out); continue

        out = dict(ai)
        out["symbol"] = sym
        out["direction"] = _normalize_direction(out.get("direction"))
        sig = str(out.get("signal", "HOLD")).upper()
        out["signal"] = sig if sig in ("BUY", "SELL", "HOLD") else "HOLD"
        out["quality_score"] = float(out.get("quality_score", avg_q) or avg_q)
        out["frames"] = out.get("frames") or [d.get("interval") for d in data]
        out["details"] = out.get("details") or data

        final.append(out)

    # 6) מיון והחזרה
    final.sort(key=lambda x: float(x.get("quality_score", 0) or 0), reverse=True)
    return final[:top_n]














































































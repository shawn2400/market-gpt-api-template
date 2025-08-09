import asyncio
import logging
import math
from typing import Optional, List, Dict

from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score
from utils.watchlist_utils import load_watchlist

# === קונפיגורציה ===
CONCURRENCY = 5
PER_SYMBOL_TIMEOUT = 25  # שניות לכל סימבול (כולל הורדה+חישוב)

# Semaphore גלובלי להגבלת מקביליות
semaphore = asyncio.Semaphore(CONCURRENCY)

REQUIRED_COLS = {"rsi", "adx", "supertrend_dir"}

def _last_valid(v) -> Optional[float]:
    """החזרת ערך מספרי תקין (לא NaN/Inf) או None."""
    if v is None:
        return None
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return fv
    except Exception:
        return None

def _normalize_trend_dir(val) -> int:
    """המרת כיוון סופרטרנד לערך תקני {1,-1}, כל דבר לא חיובי יחשב כ- DOWN."""
    try:
        return 1 if int(val) == 1 else -1
    except Exception:
        return -1

async def _safe_to_thread(func, *args, **kwargs):
    """עטיפה ל-to_thread עם טיפול חריגות."""
    return await asyncio.to_thread(func, *args, **kwargs)

async def analyze_symbol(
    symbol: str,
    interval: str = "15m",
    market_type: str = "futures",
    limit: int = 150,
    trending_only: bool = False,  # כרגע לא בשימוש לניתוח נקודתי
    with_ai: bool = False,        # לא בשימוש כאן בכוונה (AI נעשה בשכבה אחרת)
    frames: Optional[List[str]] = None
) -> Optional[Dict]:
    """
    ניתוח טכני מלא לסימבול בטיימפריים נתון.
    מחזיר dict תקני או None במקרה כשל/חוסר נתונים.
    """
    async with semaphore:
        try:
            # Timeout לכל הסיקוונס של סימבול כדי שלא ייתקעו משימות
            async def _work():
                # 1) הורדת נתונים (סינכרוני -> thread)
                df = await _safe_to_thread(get_klines, symbol=symbol, interval=interval, limit=limit, market_type=market_type)
                if df is None or df.empty:
                    logging.warning(f"[analyze_symbol] ⚠️ אין נתונים עבור {symbol}@{interval}")
                    return None

                # 2) חישוב אינדיקטורים (כבד/CPU -> thread)
                df = await _safe_to_thread(compute_indicators, df)
                if df is None or df.empty:
                    logging.warning(f"[analyze_symbol] ⚠️ compute_indicators החזיר מסגרת ריקה עבור {symbol}@{interval}")
                    return None

                # בדיקת עמודות חובה
                if not REQUIRED_COLS.issubset(df.columns):
                    logging.warning(f"[analyze_symbol] ⚠️ אינדיקטורים חסרים ({REQUIRED_COLS - set(df.columns)}) עבור {symbol}@{interval}")
                    return None

                # 3) חילוץ ערכים אחרונים תוך ניקוי NaN/Inf
                rsi_v = _last_valid(df["rsi"].iloc[-1])
                adx_v = _last_valid(df["adx"].iloc[-1])
                stdir = _normalize_trend_dir(df["supertrend_dir"].iloc[-1])

                if rsi_v is None or adx_v is None:
                    logging.warning(f"[analyze_symbol] ⚠️ ערכי RSI/ADX לא תקינים עבור {symbol}@{interval}")
                    return None

                vol_v = None
                if "volume" in df.columns:
                    vol_v = _last_valid(df["volume"].iloc[-1])

                # 4) ציון איכות (כבד/CPU -> thread)
                score = await _safe_to_thread(compute_quality_score, df)
                if score is None:
                    logging.warning(f"[analyze_symbol] ⚠️ compute_quality_score החזיר None עבור {symbol}@{interval}")
                    return None

                direction = "LONG" if stdir == 1 else "SHORT"
                trend = "UP" if stdir == 1 else "DOWN"

                # pattern אופציונלי
                pattern = "unknown"
                if "pattern" in df.columns:
                    try:
                        pattern = str(df["pattern"].iloc[-1])
                    except Exception:
                        pass

                return {
                    "symbol": symbol,
                    "interval": interval,
                    "quality_score": float(score),
                    "rsi": round(rsi_v, 2),
                    "adx": round(adx_v, 2),
                    "trend": trend,
                    "direction": direction,
                    "volume": round(vol_v, 2) if vol_v is not None else None,
                    "market": market_type,
                    "frames": frames or [],
                    "indicators": {
                        "rsi": round(rsi_v, 2),
                        "adx": round(adx_v, 2),
                        "pattern": pattern
                    }
                }

            return await asyncio.wait_for(_work(), timeout=PER_SYMBOL_TIMEOUT)

        except asyncio.TimeoutError:
            logging.error(f"[analyze_symbol] ⏱️ Timeout עבור {symbol}@{interval} (>{PER_SYMBOL_TIMEOUT}s)")
            return None
        except Exception as e:
            logging.error(f"[analyze_symbol] ❌ שגיאה בניתוח {symbol}@{interval}: {e}", exc_info=True)
            return None

async def scan_all(
    interval: str = "15m",
    min_quality: int = 6,
    top: int = 10,
    symbols: Optional[List[str]] = None,
    market_type: str = "futures"
) -> List[Dict]:
    """
    סריקה אסינכרונית לכל הסימבולים בטיימפריים מסוים.
    מחזיר רשימת טריידים עם ציון איכות ≥ min_quality, ממוינים יורד, מוגבלים ל-top.
    """
    try:
        if not symbols:
            raw_watchlist = load_watchlist() or []
            # תמיכה בפורמט: [{'symbol': 'BTCUSDT', ...}, ...]
            symbols = [x.get("symbol") for x in raw_watchlist if isinstance(x, dict) and x.get("symbol")]
        # ייחוד וסינון None/ריקים
        symbols = [s for s in dict.fromkeys(symbols or []) if s]
        if not symbols:
            logging.warning("[scan_all] ⚠️ אין סמלים לסריקה.")
            return []

        logging.info(f"[scan_all] 🚀 סורק {len(symbols)} סמלים ({market_type}) בטיימפריים {interval}...")

        tasks = [analyze_symbol(symbol=sym, interval=interval, market_type=market_type) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # סינון לפי איכות + ניטרול None
        filtered = [r for r in results if r and float(r.get("quality_score", 0)) >= float(min_quality)]

        # מיון יורד לפי איכות
        sorted_results = sorted(filtered, key=lambda x: float(x["quality_score"]), reverse=True)

        logging.info(f"[scan_all] ✅ נמצאו {len(sorted_results)} טריידים עם ציון ≥ {min_quality}")
        return sorted_results[:top]

    except Exception as e:
        logging.error(f"[scan_all] ❌ שגיאה בסריקה: {e}", exc_info=True)
        return []




































































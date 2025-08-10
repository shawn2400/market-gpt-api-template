# utils/scanner_utils.py
import asyncio
import logging
from typing import Optional, Dict, List, Any

import pandas as pd

from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score

# מקביליות בטוחה לניתוחים (לכל תהליך)
semaphore = asyncio.Semaphore(5)

def _validate_df(df: pd.DataFrame, symbol: str, interval: str) -> bool:
    """
    ולידציה בסיסית ל-DataFrame לפני חישובי אינדיקטורים.
    """
    if df is None or df.empty:
        logging.warning(f"[analyze_symbol] ⚠️ אין נתונים עבור {symbol}@{interval}")
        return False

    required_cols = {"open", "high", "low", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        logging.warning(f"[analyze_symbol] ⚠️ חסרות עמודות בסיס עבור {symbol}@{interval}: {missing}")
        return False

    return True

def _extract_last_fields(df: pd.DataFrame) -> Dict[str, Any]:
    """
    שליפת ערכים אחרונים בצורה בטוחה מה-DataFrame לאחר compute_indicators.
    """
    last = df.iloc[-1]

    def f(x, default=0.0):
        try:
            return float(x)
        except Exception:
            return float(default)

    out = {
        "close": f(last.get("close"), 0.0),
        "rsi": round(f(last.get("rsi"), 50.0), 2),
        "adx": round(f(last.get("adx"), 20.0), 2),
        "volume": round(f(last.get("volume"), 0.0), 2),
        "atr": round(f(last.get("atr"), 0.0), 6),
        "macd": f(last.get("macd"), 0.0),
        "macd_signal": f(last.get("macd_signal"), 0.0),
        "macd_hist": f(last.get("macd_hist"), 0.0),
        "ema_21": f(last.get("ema_21"), last.get("close")),
        "ema_50": f(last.get("ema_50"), last.get("close")),
        "vwap": f(last.get("vwap"), last.get("close")),
        "volume_mean": f(last.get("volume_mean"), 1.0),
    }
    if "pattern" in df.columns:
        try:
            out["pattern"] = df["pattern"].iloc[-1]
        except Exception:
            out["pattern"] = "unknown"
    return out

async def analyze_symbol(
    symbol: str,
    interval: str = "15m",
    market_type: str = "futures",
    limit: int = 150,
    trending_only: bool = False,  # נשמר לתאימות
    with_ai: bool = False,        # נשמר לתאימות; לא בשימוש כאן
    frames: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    מבצע ניתוח טכני מלא לסימבול בטיימפריים נתון.
    מחזיר dict עם פרטי ניתוח, כולל אינדיקטורים, כיוון וציון איכות.
    במקרה כשל – מחזיר None (לא זורק חריגה).
    """
    try:
        async with semaphore:
            # --- שליפת נתונים ---
            limit = max(120, int(limit or 150))
            df = get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit,
                market_type=market_type,
            )
            if not _validate_df(df, symbol, interval):
                return None

            # --- חישוב אינדיקטורים ---
            df = compute_indicators(df)
            if df is None or df.empty:
                logging.warning(f"[analyze_symbol] ⚠️ compute_indicators החזיר DataFrame ריק עבור {symbol}@{interval}")
                return None

            req = {"rsi", "adx", "supertrend_dir", "volume"}
            if not req.issubset(df.columns):
                logging.warning(f"[analyze_symbol] ⚠️ אינדיקטורים חסרים עבור {symbol}@{interval}: {req - set(df.columns)}")
                return None

            # --- ציון איכות ---
            score = float(compute_quality_score(df))

            # --- כיוון/מגמה ---
            try:
                st_dir = int(df["supertrend_dir"].iloc[-1])
            except Exception:
                st_dir = 1
            direction = "LONG" if st_dir == 1 else "SHORT"
            trend = "UP" if st_dir == 1 else "DOWN"

            # --- שליפת מדדים אחרונים ---
            last = _extract_last_fields(df)

            # החזרה – גם top-level (לתאימות עם analyze_with_ai), וגם nested תחת "indicators"
            result: Dict[str, Any] = {
                "symbol": str(symbol).upper(),
                "interval": interval,
                "market": market_type,
                "frames": frames or [],
                "quality_score": round(score, 2),
                "trend": trend,
                "direction": direction,

                # top-level (נדרש ע"י ai_analysis)
                "rsi": last["rsi"],
                "adx": last["adx"],
                "atr": last["atr"],
                "volume": last["volume"],

                # אקסטרות אם תרצה להשתמש בהמשך
                "close": last["close"],
                "macd": last["macd"],
                "macd_signal": last["macd_signal"],
                "macd_hist": last["macd_hist"],
                "ema_21": last["ema_21"],
                "ema_50": last["ema_50"],
                "vwap": last["vwap"],
                "volume_mean": last["volume_mean"],

                # בלוק מאורגן לשימושי UI/דיבוג
                "indicators": {
                    "rsi": last["rsi"],
                    "adx": last["adx"],
                    "atr": last["atr"],
                    "macd": last["macd"],
                    "macd_signal": last["macd_signal"],
                    "macd_hist": last["macd_hist"],
                    "ema_21": last["ema_21"],
                    "ema_50": last["ema_50"],
                    "vwap": last["vwap"],
                    "volume": last["volume"],
                    "volume_mean": last["volume_mean"],
                    "pattern": last.get("pattern", "unknown"),
                },
            }

            # (אופציונלי) trending_only – לא מסננים כאן כדי להשאיר החלטה לאגרגטור
            return result

    except Exception as e:
        logging.error(f"[analyze_symbol] ❌ שגיאה בניתוח {symbol}@{interval}: {e}", exc_info=True)
        return None






































































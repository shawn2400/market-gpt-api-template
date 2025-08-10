# utils/get_klines.py
import time
import logging
from typing import Optional
import pandas as pd

from binance.exceptions import BinanceAPIException, BinanceRequestException
import requests.exceptions

try:
    from utils import config
    _MIN_LIMIT = 120
    _MAX_LIMIT = 1500
    _BACKOFF_BASE = float(getattr(config, "BINANCE_BACKOFF_BASE", 0.7))
    _MAX_RETRIES = int(getattr(config, "BINANCE_MAX_RETRIES", 5))
except Exception:
    _MIN_LIMIT = 120
    _MAX_LIMIT = 1500
    _BACKOFF_BASE = 0.7
    _MAX_RETRIES = 5

# נשתמש ב-client הגלובלי עם ה-Session/Headers
from utils.binance_client import get_client

def _fetch_klines_with_retry(
    market: str,
    symbol: str,
    interval: str,
    limit: int,
    start_time: Optional[int],
    end_time: Optional[int],
) -> list:
    c = get_client()
    attempt = 0
    last_exc = None
    while attempt <= _MAX_RETRIES:
        try:
            if market == "futures":
                return c.futures_klines(
                    symbol=symbol,
                    interval=interval,
                    limit=limit,
                    startTime=start_time,
                    endTime=end_time
                )
            elif market == "spot":
                return c.get_klines(
                    symbol=symbol,
                    interval=interval,
                    limit=limit,
                    startTime=start_time,
                    endTime=end_time
                )
            else:
                raise ValueError(f"Unsupported market_type: {market}")
        except (requests.exceptions.RequestException, BinanceRequestException) as e:
            last_exc = e
            delay = _BACKOFF_BASE * (2 ** attempt)
            logging.warning(f"[get_klines] 🌐 שגיאת רשת (attempt {attempt+1}/{_MAX_RETRIES+1}) עבור {symbol}@{interval}: {e}. ממתין {delay:.2f}s…")
            time.sleep(delay); attempt += 1
        except BinanceAPIException as e:
            last_exc = e
            # 403/WAF או RateLimit/זמני
            if e.status_code == 403 or "CloudFront" in str(e) or "Invalid JSON error message" in str(e) \
               or e.code in (-1003, -1015) or e.status_code in (418, 429, 503):
                delay = _BACKOFF_BASE * (2 ** attempt)
                logging.warning(f"[get_klines] ⏳ זמני/חסימה (attempt {attempt+1}/{_MAX_RETRIES+1}) עבור {symbol}@{interval}: http={getattr(e,'status_code',0)} code={getattr(e,'code',0)} → {delay:.2f}s")
                time.sleep(delay); attempt += 1
            else:
                logging.error(f"[get_klines] ❌ BinanceAPIException לא ניתן לשחזור עבור {symbol}@{interval}: code={e.code}, msg={e.message}")
                raise
        except Exception as e:
            last_exc = e
            logging.error(f"[get_klines] ❌ חריגה לא צפויה: {type(e).__name__}: {e}")
            break
    if last_exc:
        logging.error(f"[get_klines] ❌ נכשל לאחר ריטריים: {last_exc}")
    return []

def get_klines(
    symbol: str,
    interval: str = "15m",
    limit: int = 500,
    market_type: str = "futures",
    grid_base_type: str = "futures",
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    is_futures: Optional[bool] = None
) -> pd.DataFrame:
    """
    שליפת Klines (spot/futures) עם ריטריי, נורמליזציה וניקוי.
    מחזיר DataFrame עם עמודות: timestamp, open, high, low, close, volume
    (Index=timestamp, tz=UTC)
    """
    # קביעת סוג שוק
    if is_futures is not None:
        market_type = "futures" if is_futures else "spot"
    mt = (market_type or "futures").lower().strip()
    if mt == "grid":
        mt = grid_base_type if grid_base_type in ("futures", "spot") else "futures"
    if mt not in ("futures", "spot"):
        logging.error(f"[get_klines] ❌ סוג שוק לא נתמך: {mt}")
        return pd.DataFrame()

    sym = (symbol or "").upper().strip()
    if not sym:
        logging.error("[get_klines] ❌ סימבול ריק.")
        return pd.DataFrame()

    itv = (interval or "15m").strip()
    if limit is None or limit < _MIN_LIMIT:
        logging.info(f"[get_klines] ℹ️ limit קטן מדי ({limit}); מגדיל ל-{_MIN_LIMIT} עבור {sym}")
        limit = _MIN_LIMIT
    if limit > _MAX_LIMIT:
        logging.info(f"[get_klines] ℹ️ limit גדול ({limit}); חותך ל-{_MAX_LIMIT} עבור {sym}")
        limit = _MAX_LIMIT

    try:
        raw = _fetch_klines_with_retry(
            market=mt,
            symbol=sym,
            interval=itv,
            limit=limit,
            start_time=start_time,
            end_time=end_time
        )

        if not raw or len(raw) < 10:
            logging.warning(f"[get_klines] ⚠️ נתוני Klines ריקים/מועטים ({len(raw) if raw else 0}) עבור {sym} ({mt})")
            return pd.DataFrame()

        # בניית DataFrame
        df = pd.DataFrame(raw, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_volume", "taker_buy_quote_volume", "ignore"
        ])[["timestamp", "open", "high", "low", "close", "volume"]].copy()

        # טיפוסי נתונים וניקוי
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df.sort_values("timestamp", inplace=True)
        df.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)

        nan_before = df.isna().sum().sum()
        if nan_before > 0:
            logging.warning(f"[get_klines] ⚠️ נמצאו {nan_before} NaN עבור {sym} – ממלא ffill/bfill")
            df.ffill(inplace=True); df.bfill(inplace=True)
        df.dropna(inplace=True)

        if len(df) < _MIN_LIMIT // 2:
            logging.warning(f"[get_klines] ⚠️ מעט מדי נרות לאחר סינון ({len(df)}) עבור {sym} ({mt})")
            return pd.DataFrame()

        df.set_index("timestamp", inplace=True)
        logging.info(f"[get_klines] ✅ {sym} ({itv}, {mt}): {len(df)} נרות")
        return df

    except (requests.exceptions.RequestException, BinanceRequestException) as e:
        logging.error(f"[get_klines] ❌ שגיאת רשת עבור {sym}@{itv}: {e}")
        return pd.DataFrame()
    except BinanceAPIException as e:
        logging.error(f"[get_klines] ❌ BinanceAPIException עבור {sym}@{itv}: code={e.code}, msg={e.message}")
        return pd.DataFrame()
    except Exception as e:
        logging.error(f"[get_klines] ❌ שגיאה לא צפויה עבור {sym}@{itv}: {type(e).__name__} – {e}")
        return pd.DataFrame()

















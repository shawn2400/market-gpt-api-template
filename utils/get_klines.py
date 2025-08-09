# utils/get_klines.py

import time
import logging
from typing import Optional
import pandas as pd

try:
    from utils.binance_client import client as _GLOBAL_CLIENT
except Exception:
    _GLOBAL_CLIENT = None

from binance.client import Client as _BinanceClient
from binance.exceptions import BinanceAPIException, BinanceRequestException
import requests.exceptions

MIN_LIMIT = 120
MAX_LIMIT = 1500  # תקרת בטיחות

# === עזר: יצירת לקוח במצב Public-Only במקרה שאין client ===
def _ensure_client():
    if _GLOBAL_CLIENT is not None:
        return _GLOBAL_CLIENT
    # Fallback בטוח – Public בלבד (מספיק ל־klines)
    c = _BinanceClient(None, None, tld="com")
    c.FUTURES_URL = "https://fapi.binance.com"
    logging.warning("[get_klines] ⚠️ Binance client לא מאותחל – מפעיל Public-Only fallback.")
    return c

def _fetch_klines_with_retry(
    client,
    market: str,
    symbol: str,
    interval: str,
    limit: int,
    start_time: Optional[int],
    end_time: Optional[int],
    max_retries: int = 4,
    base_backoff: float = 0.6
):
    """
    קריאת klines עם ריטריי אקספוננציאלי לשגיאות רשת/RateLimit.
    """
    attempt = 0
    last_exc = None
    while attempt <= max_retries:
        try:
            if market == "futures":
                return client.futures_klines(
                    symbol=symbol,
                    interval=interval,
                    limit=limit,
                    startTime=start_time,
                    endTime=end_time
                )
            elif market == "spot":
                return client.get_klines(
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
            delay = base_backoff * (2 ** attempt)
            logging.warning(f"[get_klines] 🌐 שגיאת רשת (attempt {attempt+1}/{max_retries+1}) עבור {symbol}@{interval}: {e}. ממתין {delay:.2f}s...")
            time.sleep(delay)
            attempt += 1
        except BinanceAPIException as e:
            last_exc = e
            # קודי Rate Limit/זמנית – כדאי לנסות שוב
            if e.code in (-1003, -1015) or e.status_code in (418, 429, 503):
                delay = base_backoff * (2 ** attempt)
                logging.warning(f"[get_klines] ⏳ RateLimit/API (attempt {attempt+1}/{max_retries+1}) עבור {symbol}@{interval}: {e}. ממתין {delay:.2f}s...")
                time.sleep(delay)
                attempt += 1
            else:
                logging.error(f"[get_klines] ❌ BinanceAPIException לא ניתן לשחזור עבור {symbol}@{interval}: code={e.code}, msg={e.message}")
                raise
        except Exception as e:
            last_exc = e
            logging.error(f"[get_klines] ❌ חריגה לא צפויה בשליפת klines עבור {symbol}@{interval}: {type(e).__name__}: {e}")
            break

    if last_exc:
        raise last_exc
    return None

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
    מחזיר DataFrame עם עמודות: timestamp, open, high, low, close, volume (Index=timestamp, tz=UTC)
    """
    # --- קביעת סוג שוק ---
    if is_futures is not None:
        market_type = "futures" if is_futures else "spot"

    mt = (market_type or "futures").lower().strip()
    if mt == "grid":
        mt = grid_base_type if grid_base_type in ("futures", "spot") else "futures"

    if mt not in ("futures", "spot"):
        logging.error(f"[get_klines] ❌ סוג שוק לא נתמך: {mt}")
        return pd.DataFrame()

    # --- נורמליזציה של פרמטרים ---
    sym = (symbol or "").upper().strip()
    if not sym:
        logging.error("[get_klines] ❌ סימבול ריק.")
        return pd.DataFrame()

    itv = (interval or "15m").strip()
    if limit is None or limit < MIN_LIMIT:
        logging.info(f"[get_klines] ℹ️ limit קטן מדי ({limit}); מגדיל ל-{MIN_LIMIT} עבור {sym}")
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        logging.info(f"[get_klines] ℹ️ limit גדול מאוד ({limit}); חותך ל-{MAX_LIMIT} עבור {sym}")
        limit = MAX_LIMIT

    client = _ensure_client()
    if client is None:
        logging.error("[get_klines] ❌ אין Binance client זמין כלל.")
        return pd.DataFrame()

    try:
        raw = _fetch_klines_with_retry(
            client=client,
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
        ])[
            ["timestamp", "open", "high", "low", "close", "volume"]
        ].copy()

        # טיפוסי נתונים וניקוי
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # מיון, הסרת כפילויות, מילוי חסרים שמרני
        df.sort_values("timestamp", inplace=True)
        df.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)

        nan_before = df.isna().sum().sum()
        if nan_before > 0:
            logging.warning(f"[get_klines] ⚠️ נמצאו {nan_before} NaN עבור {sym} – ממלא ffill/bfill")
            df.ffill(inplace=True)
            df.bfill(inplace=True)

        # הסרת שורות בעייתיות לאחר ניסיון מילוי
        df.dropna(inplace=True)

        if len(df) < MIN_LIMIT // 2:
            logging.warning(f"[get_klines] ⚠️ מעט מדי נרות לאחר סינון ({len(df)}) עבור {sym} ({mt})")
            return pd.DataFrame()

        # הצבה כאינדקס
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














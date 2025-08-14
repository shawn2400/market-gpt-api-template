# utils/get_klines.py
import time
import logging
from typing import Optional, List, Any
import pandas as pd

from utils import config

# REST fallback מהיר (מודע לבאן/Retry-After) דרך שכבת ws_fallback
from utils.ws_fallback import snapshot_klines_df
# מודעות־באן גם לשכבת python-binance (הפעלת cooldown דיפולטי כשמזהים BAN)
try:
    from utils.ws_fallback import _rest_status_is_ban as _is_ban, _note_rest_ban as _ban_cooldown  # type: ignore
except Exception:
    _is_ban = None
    _ban_cooldown = None

# נסה להשתמש בלקוח הגלובלי (אם קיים)
try:
    from utils.binance_client import client as _GLOBAL_CLIENT
except Exception:
    _GLOBAL_CLIENT = None

# שגיאות רשת/בינאנס
from binance.client import Client as _BinanceClient
from binance.exceptions import BinanceAPIException, BinanceRequestException
import requests.exceptions

MIN_LIMIT = 120
MAX_LIMIT = 1500  # תקרת בטיחות

def _ensure_client():
    """
    יוצר לקוח python-binance אם אין גלובלי — Public בלבד (מספיק ל-klines).
    הערה: הפונקציה סינכרונית. אם אתם קוראים מתוך async, הריצו דרך asyncio.to_thread.
    """
    if _GLOBAL_CLIENT is not None:
        return _GLOBAL_CLIENT
    c = _BinanceClient(None, None, tld="com")
    try:
        c.FUTURES_URL = getattr(config, "BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
    except Exception:
        c.FUTURES_URL = "https://fapi.binance.com"
    try:
        # להשלמת תמונה — אם צריך גם SPOT
        c.API_URL = getattr(config, "BINANCE_SPOT_HTTP_BASE", "https://api.binance.com")
    except Exception:
        pass
    logging.warning("[get_klines] ⚠️ Binance client לא מאותחל – מפעיל Public-Only fallback.")
    return c

def _normalize(symbol: str, interval: str, limit: Optional[int],
               market_type: str, grid_base_type: str, is_futures: Optional[bool]):
    """
    נורמליזציה של פרמטרים והחזרת ערכים בטוחים.
    """
    if is_futures is not None:
        mt = "futures" if is_futures else "spot"
    else:
        mt = (market_type or "futures").lower().strip()

    if mt == "grid":
        mt = grid_base_type if grid_base_type in ("futures", "spot") else "futures"
    if mt not in ("futures", "spot"):
        raise ValueError(f"Unsupported market_type: {mt}")

    sym = (symbol or "").upper().strip()
    if not sym:
        raise ValueError("Empty symbol")

    itv = (interval or getattr(config, "DEFAULT_INTERVAL", "15m")).strip()

    lim = int(limit or MIN_LIMIT)
    if lim < MIN_LIMIT:
        logging.info(f"[get_klines] ℹ️ limit קטן מדי ({lim}); מגדיל ל-{MIN_LIMIT} עבור {sym}")
        lim = MIN_LIMIT
    if lim > MAX_LIMIT:
        logging.info(f"[get_klines] ℹ️ limit גדול מאוד ({lim}); חותך ל-{MAX_LIMIT} עבור {sym}")
        lim = MAX_LIMIT

    return sym, itv, lim, mt

def _to_df(raw: List[List[Any]]) -> pd.DataFrame:
    """
    המרת klines גולמי ל-DataFrame נקי וממויין.
    """
    if not raw or len(raw) < 5:
        return pd.DataFrame()

    df = pd.DataFrame(raw, columns=[
        "timestamp","open","high","low","close","volume",
        "close_time","quote_asset_volume","number_of_trades",
        "taker_buy_base_volume","taker_buy_quote_volume","ignore"
    ])[["timestamp","open","high","low","close","volume"]].copy()

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ("open","high","low","close","volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df.sort_values("timestamp", inplace=True)
    df.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)

    if df.isna().values.any():
        df.ffill(inplace=True)
        df.bfill(inplace=True)

    df.dropna(inplace=True)
    if len(df) < MIN_LIMIT // 2:
        logging.warning(f"[get_klines] ⚠️ מעט מדי נרות לאחר סינון ({len(df)})")
        return pd.DataFrame()

    df.set_index("timestamp", inplace=True)
    return df

def _fetch_klines_with_retry(client,
                             market: str,
                             symbol: str,
                             interval: str,
                             limit: int,
                             start_time: Optional[int],
                             end_time: Optional[int],
                             max_retries: int = 5,
                             base_backoff: float = 0.6):
    """
    נסיונות ריטריי סינכרוניים ל-python-binance.
    הערה: אם קוראים מתוך async – הריצו כל הקריאה הזו דרך asyncio.to_thread כדי לא לחסום.
    """
    attempt = 0
    last_exc = None
    while attempt <= max_retries:
        try:
            if market == "futures":
                return client.futures_klines(symbol=symbol, interval=interval, limit=limit,
                                             startTime=start_time, endTime=end_time)
            else:
                return client.get_klines(symbol=symbol, interval=interval, limit=limit,
                                         startTime=start_time, endTime=end_time)

        except (requests.exceptions.RequestException, BinanceRequestException) as e:
            last_exc = e
            delay = min(10.0, base_backoff * (2 ** attempt))
            logging.warning(f"[get_klines] 🌐 שגיאת רשת ({attempt+1}/{max_retries+1}) {symbol}@{interval}: {e} → {delay:.2f}s")
            time.sleep(delay)
            attempt += 1

        except BinanceAPIException as e:
            last_exc = e
            status = getattr(e, "status_code", 0) or 0
            code = getattr(e, "code", 0) or 0
            txt = str(e) or ""
            # BAN/rate limit אופייני: -1003, -1015, 403/418/429/503, או הודעות CloudFront
            ban_like = (code in (-1003, -1015)) or (status in (403, 418, 429, 503)) or ("CloudFront" in txt) or ("Invalid JSON error message" in txt)
            if ban_like:
                delay = min(10.0, base_backoff * (2 ** attempt))
                logging.warning(f"[get_klines] ⏳ חסימה זמנית ({attempt+1}/{max_retries+1}) {symbol}@{interval}: http={status} code={code} → {delay:.2f}s")
                # אם יש מנגנון cooldown גלובלי של REST, הפעל אותו (דיפולט) כדי לא להחמיר את הבאן
                if _ban_cooldown:
                    try:
                        _ban_cooldown(None)  # אין Response, נפעיל cooldown דיפולטי
                    except Exception:
                        pass
                time.sleep(delay)
                attempt += 1
            else:
                logging.error(f"[get_klines] ❌ BinanceAPIException לא ניתן לשחזור {symbol}@{interval}: code={code}, msg={e.message}")
                raise

        except Exception as e:
            last_exc = e
            logging.error(f"[get_klines] ❌ חריגה לא צפויה {symbol}@{interval}: {type(e).__name__}: {e}")
            break

    if last_exc:
        raise last_exc
    return None

def get_klines(symbol: str,
               interval: str = "15m",
               limit: int = 500,
               market_type: str = "futures",
               grid_base_type: str = "futures",
               start_time: Optional[int] = None,
               end_time: Optional[int] = None,
               is_futures: Optional[bool] = None) -> pd.DataFrame:
    """
    זרימת השגה יציבה:
    1) ניסיון REST ישיר (snapshot_klines_df) — מודע לבאן/Retry-After; מחזיר DF ריק בזמן cooldown.
    2) נפילה ל-python-binance עם ריטריי שמרני והפעלת cooldown דיפולטי כאשר מזוהה BAN.
    הערה: הפונקציה סינכרונית. מתוך async יש להריץ אותה דרך asyncio.to_thread.
    """
    try:
        sym, itv, lim, mt = _normalize(symbol, interval, limit, market_type, grid_base_type, is_futures)
    except Exception as e:
        logging.error(f"[get_klines] ❌ נורמליזציה נכשלה: {e}")
        return pd.DataFrame()

    # שלב 1: REST ישיר (מודע לבאן)
    try:
        df_rest = snapshot_klines_df(symbol=sym, interval=itv, limit=lim, market_type=mt)
        if not df_rest.empty:
            logging.info(f"[get_klines] ✅ {sym} ({itv}, {mt} via REST): {len(df_rest)} נרות")
            return df_rest
        logging.warning(f"[get_klines] ⚠️ REST ריק/נחסם עבור {sym}@{itv} ({mt}), נופל ל-python-binance")
    except Exception as e:
        logging.warning(f"[get_klines] ⚠️ REST snapshot נכשל עבור {sym}@{itv}: {e} — נופל ל-python-binance")

    # שלב 2: python-binance (סינכרוני)
    client = _ensure_client()
    if client is None:
        logging.error("[get_klines] ❌ אין Binance client זמין.")
        return pd.DataFrame()

    try:
        raw = _fetch_klines_with_retry(client, mt, sym, itv, lim, start_time, end_time)
        if not raw or len(raw) < 10:
            logging.warning(f"[get_klines] ⚠️ Klines ריקים/מועטים ({len(raw) if raw else 0}) עבור {sym} ({mt})")
            return pd.DataFrame()

        df = _to_df(raw)
        if df.empty:
            logging.warning(f"[get_klines] ⚠️ לאחר ניקוי — אין מספיק נתונים עבור {sym}@{itv}")
            return pd.DataFrame()

        logging.info(f"[get_klines] ✅ {sym} ({itv}, {mt} via python-binance): {len(df)} נרות")
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

































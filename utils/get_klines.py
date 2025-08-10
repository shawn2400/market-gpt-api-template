# utils/get_klines.py
# גרסה מלאה ומוקשחת: ריטריי עם backoff+ג'יטר, Fallback Public-Only עם timeout,
# נרמול/ניקוי נתונים, ופונקציית עימוד להיסטוריה עמוקה (get_klines_range)

import time
import random
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
from datetime import datetime, timezone

MIN_LIMIT = 120
MAX_LIMIT = 1500  # תקרת בטיחות


# === עזר: יצירת לקוח במצב Public-Only במקרה שאין client ===
def _ensure_client():
    if _GLOBAL_CLIENT is not None:
        return _GLOBAL_CLIENT
    # Fallback בטוח – Public בלבד (מספיק ל־klines) עם timeout סביר
    c = _BinanceClient(None, None, tld="com", requests_params={"timeout": 10})
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
    קריאת klines עם ריטריי אקספוננציאלי לשגיאות רשת/RateLimit/403-WAF.
    כולל ג'יטר כדי להפחית התנגשויות.
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
            delay = base_backoff * (2 ** attempt) + random.uniform(0, 0.35)
            logging.warning(
                f"[get_klines] 🌐 שגיאת רשת (attempt {attempt+1}/{max_retries+1}) עבור {symbol}@{interval}: {e}. "
                f"ממתין {delay:.2f}s..."
            )
            time.sleep(delay)
            attempt += 1

        except BinanceAPIException as e:
            last_exc = e
            msg = f"{e}"
            # זמני/נפוץ: 403 (CloudFront/WAF), 418/429/503, RateLimit (-1003/-1015) או invalid JSON HTML
            if (
                getattr(e, "status_code", None) in (403, 418, 429, 503)
                or getattr(e, "code", None) in (-1003, -1015)
                or "CloudFront" in msg
                or "Invalid JSON error message" in msg
            ):
                delay = base_backoff * (2 ** attempt) + random.uniform(0, 0.35)
                logging.warning(
                    f"[get_klines] ⏳ זמני/חסימה (attempt {attempt+1}/{max_retries+1}) עבור {symbol}@{interval}: "
                    f"http={getattr(e, 'status_code', '?')} code={getattr(e, 'code', '?')} → {delay:.2f}s"
                )
                time.sleep(delay)
                attempt += 1
            else:
                logging.error(
                    f"[get_klines] ❌ BinanceAPIException לא ניתן לשחזור עבור {symbol}@{interval}: "
                    f"code={e.code}, http={e.status_code}, msg={e.message}"
                )
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
        ])[["timestamp", "open", "high", "low", "close", "volume"]].copy()

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


# === Pagination: משיכת היסטוריה עמוקה בטווח תאריכים ===
def _interval_to_ms(interval: str) -> int:
    """המרת אינטרוול ל־milliseconds (תמיכה: m/h/d/w)."""
    interval = (interval or "15m").strip().lower()
    unit = interval[-1]
    try:
        n = int(interval[:-1])
    except Exception:
        n = 15 if unit == "m" else 1
    if unit == "m":
        return n * 60_000
    if unit == "h":
        return n * 3_600_000
    if unit == "d":
        return n * 86_400_000
    if unit == "w":
        return n * 7 * 86_400_000
    # ברירת מחדל: דקה
    return n * 60_000


def _to_millis(ts) -> Optional[int]:
    """
    קבלת timestamp בפורמטים: int/float (שניות או מילישניות), datetime/Pandas Timestamp, או מחרוזת ISO.
    מחזיר מילישניות (UTC).
    """
    if ts is None:
        return None
    # מספרי: אם בשניות – המר למילישניות
    if isinstance(ts, (int, float)):
        v = int(ts)
        return v * 1000 if v < 1_000_000_000_000 else v
    # datetime
    if isinstance(ts, datetime):
        dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    # נסיון לפרסר מחרוזת/טיפוס אחר דרך pandas
    try:
        dts = pd.to_datetime(ts, utc=True)
        if hasattr(dts, "to_pydatetime"):
            return int(dts.to_pydatetime().timestamp() * 1000)
    except Exception:
        pass
    raise ValueError(f"Unsupported timestamp format: {ts!r}")


def get_klines_range(
    symbol: str,
    interval: str = "15m",
    market_type: str = "futures",
    start: Optional[object] = None,   # int/float/datetime/str
    end: Optional[object] = None,     # int/float/datetime/str
    limit_per_call: int = 1000,
    max_candles: int = 10000,
    sleep_between: float = 0.20,
    grid_base_type: str = "futures",
    is_futures: Optional[bool] = None
) -> pd.DataFrame:
    """
    מושך היסטוריית Klines בטווח [start, end] עם עימוד בטוח.
    אם start לא סופק – חוזר להתנהגות get_klines (קריאת batch יחידה של אחרוני הנרות).

    החזרה: DataFrame עם אינדקס timestamp (UTC) ועמודות: open, high, low, close, volume.
    """
    # אם אין start – השתמש בקריאה יחידה (מהירה)
    if start is None:
        return get_klines(
            symbol=symbol,
            interval=interval,
            limit=min(max_candles, MAX_LIMIT),
            market_type=market_type,
            grid_base_type=grid_base_type,
            is_futures=is_futures
        )

    # קביעת סוג שוק זהה ל-get_klines
    if is_futures is not None:
        market_type = "futures" if is_futures else "spot"
    mt = (market_type or "futures").lower().strip()
    if mt == "grid":
        mt = grid_base_type if grid_base_type in ("futures", "spot") else "futures"
    if mt not in ("futures", "spot"):
        logging.error(f"[get_klines_range] ❌ סוג שוק לא נתמך: {mt}")
        return pd.DataFrame()

    sym = (symbol or "").upper().strip()
    if not sym:
        logging.error("[get_klines_range] ❌ סימבול ריק.")
        return pd.DataFrame()

    itv = (interval or "15m").strip()
    iv_ms = _interval_to_ms(itv)

    # נרמול זמנים למילישניות
    start_ms = _to_millis(start)
    end_ms = _to_millis(end) if end is not None else int(time.time() * 1000)

    if start_ms >= end_ms:
        logging.error(f"[get_klines_range] ❌ טווח זמנים לא חוקי: start>=end ({start_ms} ≥ {end_ms})")
        return pd.DataFrame()

    # נרמול limit_per_call
    limit_per_call = max(MIN_LIMIT, min(int(limit_per_call or 1000), MAX_LIMIT))
    max_candles = max(MIN_LIMIT, int(max_candles or 10000))

    client = _ensure_client()
    if client is None:
        logging.error("[get_klines_range] ❌ אין Binance client זמין כלל.")
        return pd.DataFrame()

    all_rows = []
    cur = start_ms
    total = 0
    it = 0

    logging.info(f"[get_klines_range] ⏬ מתחיל עימוד {sym} {itv} ({mt}) מ-{start_ms} עד {end_ms}...")

    while cur < end_ms and total < max_candles:
        it += 1
        try:
            raw = _fetch_klines_with_retry(
                client=client,
                market=mt,
                symbol=sym,
                interval=itv,
                limit=limit_per_call,
                start_time=cur,
                end_time=end_ms
            )
        except Exception as e:
            logging.warning(f"[get_klines_range] ⚠️ כשל זמני באיטרציה {it}: {e}. ממשיך...")
            # השהיה קצרה לפני נסיון הבא
            time.sleep(sleep_between)
            continue

        if not raw:
            logging.info(f"[get_klines_range] ℹ️ אין נתונים באיטרציה {it} (cur={cur}) — סיום.")
            break

        all_rows.extend(raw)
        total = len(all_rows)

        # קידום נקודת ההתחלה לאיטרציה הבאה
        # raw[i] = [open_time, o, h, l, c, v, close_time, ...]
        last_close_time = raw[-1][6] if len(raw[-1]) > 6 else raw[-1][0] + iv_ms - 1
        cur = int(last_close_time) + 1

        # עצירות
        if len(raw) < limit_per_call:
            logging.info(f"[get_klines_range] ✔️ התקבלו פחות מה-LIMIT באיטרציה {it} ({len(raw)}) — כנראה סוף טווח.")
            break
        if total >= max_candles:
            logging.info(f"[get_klines_range] ✔️ הגעה לתקרת max_candles={max_candles}.")
            break

        time.sleep(sleep_between)

    if not all_rows:
        logging.warning(f"[get_klines_range] ⚠️ לא נמצאו נרות עבור {sym} ({mt}).")
        return pd.DataFrame()

    # בניית DataFrame וניקוי — זהה ל-get_klines
    df = pd.DataFrame(all_rows, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_volume", "taker_buy_quote_volume", "ignore"
    ])[["timestamp", "open", "high", "low", "close", "volume"]].copy()

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df.sort_values("timestamp", inplace=True)
    df.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)

    nan_before = df.isna().sum().sum()
    if nan_before > 0:
        logging.warning(f"[get_klines_range] ⚠️ נמצאו {nan_before} NaN עבור {sym} – ממלא ffill/bfill")
        df.ffill(inplace=True)
        df.bfill(inplace=True)
    df.dropna(inplace=True)

    if len(df) > max_candles:
        df = df.tail(max_candles)

    df.set_index("timestamp", inplace=True)

    if len(df) < MIN_LIMIT // 2:
        logging.warning(f"[get_klines_range] ⚠️ מעט מדי נרות לאחר סינון ({len(df)}) עבור {sym} ({mt})")

    logging.info(f"[get_klines_range] ✅ {sym} ({itv}, {mt}): {len(df)} נרות הוחזרו")
    return df
















# utils/backtest_utils.py
from __future__ import annotations

import os
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd
import requests
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

from utils.indicators_utils import prepare_indicators_for_backtest
from utils.sl_tp_utils import calculate_sl_tp  # מחזיר (sl, tp)

load_dotenv()

# --------------- Candlestick helper ---------------

def detect_bearish_engulfing(df: pd.DataFrame) -> pd.DataFrame:
    """
    מוסיף עמודה 'bearish_engulfing' בוליאנית.
    הגדרה בסיסית: נר אדום שעוטף את גוף הנר הקודם שהיה ירוק.
    """
    df = df.copy()
    prev_green = (df['close'].shift(1) > df['open'].shift(1))
    red_now = (df['close'] < df['open'])
    engulfs = (df['open'] > df['close'].shift(1)) & (df['close'] < df['open'].shift(1))
    df['bearish_engulfing'] = (prev_green & red_now & engulfs).fillna(False)
    return df

# --------------- Quality / confidence ---------------

def compute_confidence(row: pd.Series) -> float:
    """
    ציון איכות [0..1] פשוט, מבוסס כמה אינדיקטורים נפוצים.
    מניח שהעמודות נוצרת ב־prepare_indicators_for_backtest.
    """
    score = 0
    try:
        rsi = float(row.get('rsi', 50) or 50)
        macd_hist = float(row.get('macd_hist', 0) or 0)
        adx = float(row.get('adx', 0) or 0)
        close = float(row.get('close', 0) or 0)
        ema_21 = float(row.get('ema_21', close) or close)
        volume = float(row.get('volume', 0) or 0)
        volume_mean = float(row.get('volume_mean', max(1.0, volume)) or max(1.0, volume))
        obv_trend = bool(row.get('obv_trend', False))
        vwap_trend = bool(row.get('vwap_trend', False))

        if 15 < rsi < 35 or 65 < rsi < 85: score += 1
        if abs(macd_hist) > 0: score += 1
        if adx >= 17: score += 1
        if close > ema_21: score += 1
        if volume > volume_mean * 1.3: score += 1
        if obv_trend: score += 1
        if vwap_trend: score += 1
    except Exception:
        pass
    return round(score / 7, 2)

# --------------- Core backtest ---------------

def _need_cols(df: pd.DataFrame, cols: List[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

def backtest_strategy(
    df: pd.DataFrame,
    rrr_target: float = 2.5,
    min_adx: float = 17.0,
    max_hold: int = 30,
) -> pd.DataFrame:
    """
    Backtest פשוט מבוסס אותות Long/Short:
      Long: RSI<30, MACD-Hist>0, Close>EMA21, ADX>=min_adx, StochK<20
      Short: RSI>70, MACD-Hist<0, Close<EMA21, ADX>=min_adx, Bearish Engulfing, StochK>80
    חישוב SL/TP מתקבל מ־calculate_sl_tp(entry_price, direction, atr?).
    מחזיר טבלת טריידים.
    """
    if df is None or len(df) < 5:
        raise ValueError("Not enough data to run backtest. Need at least 5 candles.")

    base_cols = ["open", "high", "low", "close", "volume"]
    _need_cols(df, base_cols)

    # הכנת אינדיקטורים
    work = prepare_indicators_for_backtest(df.copy())
    # עמודות מינימליות שהאסטרטגיה משתמשת בהן
    _need_cols(work, ["rsi", "macd_hist", "ema_21", "adx", "stoch_k"])
    # ATR אופציונלי – אם prepare_indicators הוסיף, נשתמש; אם לא, נתעלם
    atr_available = "atr" in work.columns

    # תבנית נרות
    work = detect_bearish_engulfing(work)

    # שדות תוצאה
    work["signal"] = None
    work["entry"] = None
    work["stop"] = None
    work["tp"] = None
    work["rrr"] = None
    work["exit"] = None
    work["pnl"] = None
    work["success"] = None
    work["quality_score"] = None

    n = len(work)
    for i in range(1, n):
        row = work.iloc[i]
        entry: Optional[float] = None
        stop: Optional[float] = None
        tp: Optional[float] = None
        signal: Optional[str] = None

        rsi = float(row["rsi"])
        macd_hist = float(row["macd_hist"])
        adx = float(row["adx"])
        close = float(row["close"])
        ema21 = float(row["ema_21"])
        stoch_k = float(row["stoch_k"])
        atr_val = float(row["atr"]) if atr_available and pd.notna(row["atr"]) else None

        # LONG setup
        if (rsi < 30 and macd_hist > 0 and close > ema21 and adx >= min_adx and stoch_k < 20):
            entry = close
            sl, tp = calculate_sl_tp(entry_price=entry, direction="LONG", atr=atr_val)
            signal = "LONG"

        # SHORT setup
        elif (rsi > 70 and macd_hist < 0 and close < ema21 and adx >= min_adx
              and bool(row.get("bearish_engulfing", False)) and stoch_k > 80):
            entry = close
            sl, tp = calculate_sl_tp(entry_price=entry, direction="SHORT", atr=atr_val)
            signal = "SHORT"

        if signal and entry and sl is not None and tp is not None:
            work.loc[i, "signal"] = signal
            work.loc[i, "entry"] = float(entry)
            work.loc[i, "stop"] = float(sl)
            work.loc[i, "tp"] = float(tp)
            work.loc[i, "rrr"] = float(rrr_target)
            work.loc[i, "quality_score"] = compute_confidence(row)

            # סימולציית יציאה: TP/SL או טיימאאוט עד max_hold נרות
            for j in range(i + 1, min(i + max_hold, n)):
                close_j = float(work["close"].iloc[j])
                if signal == "LONG":
                    if close_j <= sl:
                        work.loc[i, "exit"] = close_j
                        work.loc[i, "pnl"] = close_j - entry
                        work.loc[i, "success"] = False
                        break
                    if close_j >= tp:
                        work.loc[i, "exit"] = close_j
                        work.loc[i, "pnl"] = close_j - entry
                        work.loc[i, "success"] = True
                        break
                else:  # SHORT
                    if close_j >= sl:
                        work.loc[i, "exit"] = close_j
                        work.loc[i, "pnl"] = entry - close_j
                        work.loc[i, "success"] = False
                        break
                    if close_j <= tp:
                        work.loc[i, "exit"] = close_j
                        work.loc[i, "pnl"] = entry - close_j
                        work.loc[i, "success"] = True
                        break

            # אם לא הייתה יציאת TP/SL בתוך max_hold – נסגור על הנר האחרון בחלון
            if pd.isna(work.loc[i, "exit"]):
                last_close = float(work["close"].iloc[min(i + max_hold - 1, n - 1)])
                work.loc[i, "exit"] = last_close
                if signal == "LONG":
                    work.loc[i, "pnl"] = last_close - entry
                else:
                    work.loc[i, "pnl"] = entry - last_close
                work.loc[i, "success"] = bool(work.loc[i, "pnl"] > 0)

    # פלט: רק שורות עם סיגנל
    cols_out = ["timestamp", "signal", "entry", "stop", "tp", "exit", "rrr", "pnl", "success", "quality_score"]
    # תמיכה אם timestamp לא קיים: ננסה 'open_time' או נוותר על העמודה
    ts_col = "timestamp" if "timestamp" in work.columns else ("open_time" if "open_time" in work.columns else None)
    out_cols = [c for c in cols_out if c != "timestamp"]
    if ts_col:
        out_cols = [ts_col] + out_cols

    result = work[work["signal"].notnull()][out_cols].reset_index(drop=True)
    return result

# --------------- News helpers (אופציונלי לבקטסט) ---------------

def fetch_crypto_news() -> List[Dict[str, Any]]:
    api_key = os.getenv("CRYPTO_PANIC_API_KEY")
    if not api_key:
        print("[!] לא הוגדר מפתח API ל־CryptoPanic")
        return []
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={api_key}&public=true"
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        data = r.json() or {}
        return list(data.get("results", []) or [])
    except Exception as e:
        print(f"[!] שגיאה בשליפת חדשות: {e}")
        return []

def analyze_news_impact(news_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    scored_news: List[Dict[str, Any]] = []
    seen = set()
    positive_words = ["bullish", "surge", "breakout", "pump", "rally", "gain", "soar"]
    negative_words = ["bearish", "crash", "fud", "dump", "selloff", "collapse"]
    for item in news_list:
        url = (item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        title = (item.get("title") or "").lower()
        score = 0
        if any(w in title for w in positive_words): score += 1
        if any(w in title for w in negative_words): score -= 1
        scored_news.append({
            "title": item.get("title"),
            "published_at": item.get("published_at"),
            "url": url,
            "impact_score": int(score),
        })
    return scored_news

def send_email_alert(subject: str, body: str = "See attached.", attachment: Optional[str | bytes] = None) -> bool:
    try:
        EMAIL_ADDRESS = os.getenv("ALERT_EMAIL_ADDRESS")
        EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD")
        TO_EMAIL = os.getenv("ALERT_TO_EMAIL", EMAIL_ADDRESS)

        if not EMAIL_ADDRESS or not EMAIL_PASSWORD or not TO_EMAIL:
            print("[!] דילוג על שליחת מייל – פרטי התחברות חסרים")
            return False

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = TO_EMAIL
        msg.set_content(body)

        if attachment:
            if isinstance(attachment, bytes):
                msg.add_attachment(attachment, maintype="application", subtype="pdf", filename="report.pdf")
            elif isinstance(attachment, str) and os.path.exists(attachment):
                with open(attachment, "rb") as f:
                    data = f.read()
                msg.add_attachment(data, maintype="application", subtype="pdf", filename=os.path.basename(attachment))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"[!] Email failed: {e}")
        return False

# --------------- Public API ---------------

def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    return backtest_strategy(df)















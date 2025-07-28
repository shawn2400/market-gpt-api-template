# backtest_utils.py

import os
import pandas as pd
import requests
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv
from utils.indicators_utils import prepare_indicators_for_backtest

load_dotenv()

def detect_bearish_engulfing(df):
    df['bearish_engulfing'] = (
        (df['close'].shift(1) > df['open'].shift(1)) &
        (df['close'] < df['open']) &
        (df['open'] > df['close'].shift(1)) &
        (df['close'] < df['open'].shift(1))
    )
    return df

def compute_confidence(row):
    score = 0
    if 15 < row['rsi'] < 35 or 65 < row['rsi'] < 85: score += 1
    if abs(row['macd_hist']) > 0: score += 1
    if row['adx'] >= 17: score += 1
    if row['close'] > row['ema_21']: score += 1
    if row['volume'] > row['volume_mean'] * 1.3: score += 1
    if row['obv_trend']: score += 1
    if row['vwap_trend']: score += 1
    return round(score / 7, 2)

def backtest_strategy(df, rrr_target=2.5, min_adx=17):
    df = df.copy()

    if len(df) < 5:
        raise ValueError("Not enough data to run backtest. Need at least 5 candles.")

    df = prepare_indicators_for_backtest(df)
    df = detect_bearish_engulfing(df)

    df['signal'] = None
    df['entry'] = None
    df['stop'] = None
    df['tp'] = None
    df['rrr'] = None
    df['exit'] = None
    df['pnl'] = None
    df['success'] = None
    df['quality_score'] = None

    for i in range(1, len(df)):
        row = df.iloc[i]
        entry = stop = tp = None
        signal = None

        if row['rsi'] < 30 and row['macd_hist'] > 0 and row['close'] > row['ema_21'] and row['adx'] >= min_adx and row['stoch_k'] < 20:
            entry = row['close']
            stop = entry * 0.985
            tp = entry + (rrr_target * (entry - stop))
            signal = "LONG"

        elif row['rsi'] > 70 and row['macd_hist'] < 0 and row['close'] < row['ema_21'] and row['adx'] >= min_adx and row['bearish_engulfing'] and row['stoch_k'] > 80:
            entry = row['close']
            stop = entry * 1.015
            tp = entry - (rrr_target * (stop - entry))
            signal = "SHORT"

        if signal:
            df.at[i, 'signal'] = signal
            df.at[i, 'entry'] = entry
            df.at[i, 'stop'] = stop
            df.at[i, 'tp'] = tp
            df.at[i, 'rrr'] = rrr_target
            df.at[i, 'quality_score'] = compute_confidence(row)

            max_hold = 30
            for j in range(i + 1, min(i + max_hold, len(df))):
                close_price = df['close'].iloc[j]
                if signal == 'LONG':
                    if close_price <= stop:
                        df.at[i, 'exit'] = close_price
                        df.at[i, 'pnl'] = close_price - entry
                        df.at[i, 'success'] = False
                        break
                    elif close_price >= tp:
                        df.at[i, 'exit'] = close_price
                        df.at[i, 'pnl'] = close_price - entry
                        df.at[i, 'success'] = True
                        break
                else:
                    if close_price >= stop:
                        df.at[i, 'exit'] = close_price
                        df.at[i, 'pnl'] = entry - close_price
                        df.at[i, 'success'] = False
                        break
                    elif close_price <= tp:
                        df.at[i, 'exit'] = close_price
                        df.at[i, 'pnl'] = entry - close_price
                        df.at[i, 'success'] = True
                        break

    result = df[df['signal'].notnull()][[
        'timestamp', 'signal', 'entry', 'stop', 'tp', 'exit',
        'rrr', 'pnl', 'success', 'quality_score'
    ]].reset_index(drop=True)

    return result

def fetch_crypto_news():
    api_key = os.getenv("CRYPTO_PANIC_API_KEY")
    if not api_key:
        print("[!] לא הוגדר מפתח API ל־CryptoPanic")
        return []
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={api_key}&public=true"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json().get("results", [])
    except Exception as e:
        print(f"[!] שגיאה בשליפת חדשות: {e}")
        return []

def analyze_news_impact(news_list):
    scored_news = []
    for item in news_list:
        score = 0
        title = item.get("title", "").lower()
        positive_words = ["bullish", "surge", "breakout", "pump", "rally", "gain", "soar"]
        negative_words = ["bearish", "crash", "fud", "dump", "selloff", "collapse"]
        if any(w in title for w in positive_words):
            score += 1
        if any(w in title for w in negative_words):
            score -= 1
        scored_news.append({
            "title": item.get("title"),
            "published_at": item.get("published_at"),
            "url": item.get("url"),
            "impact_score": score
        })
    return scored_news

def send_email_alert(subject, body="See attached.", attachment=None):
    try:
        EMAIL_ADDRESS = os.getenv("ALERT_EMAIL_ADDRESS")
        EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD")
        TO_EMAIL = os.getenv("ALERT_TO_EMAIL", EMAIL_ADDRESS)

        if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
            print("[!] דילוג על שליחת מייל – פרטי התחברות חסרים")
            return

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = TO_EMAIL
        msg.set_content(body)

        if attachment:
            msg.add_attachment(
                attachment,
                maintype="application",
                subtype="pdf",
                filename="report.pdf"
            )

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)

    except Exception as e:
        print(f"[!] Email failed: {e}")

def run_backtest(df):
    return backtest_strategy(df)












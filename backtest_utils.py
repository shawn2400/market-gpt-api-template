# updated_backtest_utils.py

import os
import pandas as pd
import requests
import smtplib
from email.message import EmailMessage
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from dotenv import load_dotenv

load_dotenv()

def detect_bearish_engulfing(df):
    df['bearish_engulfing'] = (
        (df['close'].shift(1) > df['open'].shift(1)) &
        (df['close'] < df['open']) &
        (df['open'] > df['close'].shift(1)) &
        (df['close'] < df['open'].shift(1))
    )
    return df

def backtest_strategy(df, rrr_target=2.5, min_adx=17):
    df = df.copy()

    if len(df) < 30:
        raise ValueError("Not enough data to run backtest. Need at least 30 candles.")

    df['ema_21'] = EMAIndicator(df['close'], window=21).ema_indicator()
    df['macd'] = MACD(df['close']).macd_diff()
    df['rsi'] = RSIIndicator(df['close']).rsi()
    df['adx'] = ADXIndicator(df['high'], df['low'], df['close']).adx()
    df['atr'] = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range()
    df['bb_upper'] = BollingerBands(df['close']).bollinger_hband()
    df['bb_lower'] = BollingerBands(df['close']).bollinger_lband()
    df['volume_mean'] = df['volume'].rolling(10).mean()
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
        atr = row['atr']
        adx = row['adx']
        rsi = row['rsi']
        macd = row['macd']
        price = row['close']
        engulf = row['bearish_engulfing']

        score = 0
        if 15 < rsi < 35 or 65 < rsi < 85: score += 1
        if abs(macd) > 0: score += 1
        if adx >= min_adx: score += 1
        if price > row['ema_21']: score += 1
        if row['volume'] > row['volume_mean'] * 1.3: score += 1

        entry = stop = tp = None
        signal = None

        if rsi < 30 and macd > 0 and price > row['ema_21'] and adx >= min_adx:
            entry = price
            stop = entry * 0.985
            tp = entry + (rrr_target * (entry - stop))
            signal = "LONG"

        elif rsi > 70 and macd < 0 and price < row['ema_21'] and adx >= min_adx and engulf:
            entry = price
            stop = entry * 1.015
            tp = entry - (rrr_target * (stop - entry))
            signal = "SHORT"

        if signal:
            df.at[i, 'signal'] = signal
            df.at[i, 'entry'] = entry
            df.at[i, 'stop'] = stop
            df.at[i, 'tp'] = tp
            df.at[i, 'rrr'] = rrr_target
            df.at[i, 'quality_score'] = round(score / 5, 2)

            max_hold = 30  # סימולציה של "אם נשארנו עוד"
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







import os
import time
import pandas as pd
from binance.client import Client
from binance.enums import *
from dotenv import load_dotenv
from utils.quality_score import compute_quality_score
from utils.binance_client import client
import ta

load_dotenv()

def compute_indicators(df):
    try:
        df['EMA21'] = ta.trend.EMAIndicator(close=df['close'], window=21).ema_indicator()
        df['EMA50'] = ta.trend.EMAIndicator(close=df['close'], window=50).ema_indicator()
        df['RSI'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        macd = ta.trend.MACD(close=df['close'])
        df['MACD'] = macd.macd()
        df['MACD_signal'] = macd.macd_signal()
        adx = ta.trend.ADXIndicator(high=df['high'], low=df['low'], close=df['close'])
        df['ADX'] = adx.adx()
        atr = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'])
        df['ATR'] = atr.average_true_range()
        df['volume_mean'] = df['volume'].rolling(window=20).mean()
        df.dropna(inplace=True)

        signal = None
        if df['RSI'].iloc[-1] > 55 and df['MACD'].iloc[-1] > df['MACD_signal'].iloc[-1] and df['ADX'].iloc[-1] > 17 and df['close'].iloc[-1] > df['EMA21'].iloc[-1]:
            signal = "LONG"
        elif df['RSI'].iloc[-1] < 45 and df['MACD'].iloc[-1] < df['MACD_signal'].iloc[-1] and df['ADX'].iloc[-1] > 17 and df['close'].iloc[-1] < df['EMA21'].iloc[-1]:
            signal = "SHORT"

        return {"signal": signal, "df": df}
    except Exception as e:
        print(f"[!] שגיאה בחישוב אינדיקטורים: {e}")
        return {"signal": None, "df": df}

def scan_all_futures_live(budget_usd=100):
    try:
        print("🚀 התחלת סריקה חיה")
        symbols = [
            s['symbol']
            for s in client.futures_exchange_info()['symbols']
            if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT'
        ]
        print(f"🔢 נמצאו {len(symbols)} סמלים לבדיקה")
    except Exception as e:
        print(f"[!] שגיאה בקבלת רשימת סמלים: {e}")
        return []

    results = []

    for i, symbol in enumerate(symbols[:30]):
        try:
            start_time = time.time()
            print(f"[{i}] 🔍 בודק {symbol}...")

            klines = client.futures_klines(
                symbol=symbol,
                interval=Client.KLINE_INTERVAL_15MINUTE,
                limit=100
            )

            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close',
                'volume', 'close_time', 'quote_asset_volume',
                'num_trades', 'taker_buy_base_asset_volume',
                'taker_buy_quote_asset_volume', 'ignore'
            ])
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)

            recent_vol = df['volume'].iloc[-1]
            avg_vol = df['volume'].rolling(20).mean().iloc[-1]
            if recent_vol < 0.5 * avg_vol:
                print(f"⚠️ דילוג על {symbol} — נפח מסחר נמוך ({recent_vol:.2f} < {avg_vol:.2f})")
                continue

            indicators = compute_indicators(df)
            signal = indicators['signal']
            df = indicators['df']

            score = compute_quality_score(df)
            duration = round(time.time() - start_time, 2)
            print(f"✅ סיים {symbol} תוך {duration} שניות")

            if signal and score >= 4:
                price = float(df['close'].iloc[-1])
                tp = round(price * 1.03, 2)
                sl = round(price * 0.98, 2)

                results.append({
                    "symbol": symbol,
                    "entry": price,
                    "take_profit": tp,
                    "stop_loss": sl,
                    "signal": signal,
                    "quality_score": score
                })

            time.sleep(0.1)

        except Exception as e:
            print(f"[!] שגיאה ב־{symbol}: {e}")
            continue

    print(f"✅ סיום סריקה. נמצאו {len(results)} תוצאות.")
    sorted_results = sorted(results, key=lambda x: x['quality_score'], reverse=True)
    return sorted_results























import pandas as pd
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange

def backtest_strategy(df, rrr_target=2.0):
    df = df.copy()
    df['ema_21'] = EMAIndicator(df['close'], window=21).ema_indicator()
    df['macd'] = MACD(df['close']).macd_diff()
    df['rsi'] = RSIIndicator(df['close']).rsi()
    df['adx'] = ADXIndicator(df['high'], df['low'], df['close']).adx()
    df['atr'] = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range()

    df['signal'] = None
    df['entry'] = None
    df['stop'] = None
    df['tp'] = None
    df['rrr'] = None
    df['exit'] = None
    df['pnl'] = None
    df['success'] = None

    for i in range(1, len(df)):
        if df['signal'].iloc[i - 1] is not None:
            continue  # למנוע כניסה כפולה ברצף

        row = df.iloc[i]
        atr = df['atr'].iloc[i]

        # תנאי LONG
        if (
            row['rsi'] < 30 and
            row['macd'] > 0 and
            row['close'] > row['ema_21'] and
            row['adx'] > 20
        ):
            entry = row['close']
            stop = entry - atr
            tp = entry + (rrr_target * (entry - stop))
            df.at[i, 'signal'] = 'LONG'
            df.at[i, 'entry'] = entry
            df.at[i, 'stop'] = stop
            df.at[i, 'tp'] = tp
            df.at[i, 'rrr'] = rrr_target

            # חיפוש יציאה
            for j in range(i + 1, min(i + 30, len(df))):
                price = df['close'].iloc[j]
                if price <= stop:
                    df.at[i, 'exit'] = price
                    df.at[i, 'pnl'] = price - entry
                    df.at[i, 'success'] = False
                    break
                elif price >= tp:
                    df.at[i, 'exit'] = price
                    df.at[i, 'pnl'] = price - entry
                    df.at[i, 'success'] = True
                    break

        # תנאי SHORT
        elif (
            row['rsi'] > 70 and
            row['macd'] < 0 and
            row['close'] < row['ema_21'] and
            row['adx'] > 20
        ):
            entry = row['close']
            stop = entry + atr
            tp = entry - (rrr_target * (stop - entry))
            df.at[i, 'signal'] = 'SHORT'
            df.at[i, 'entry'] = entry
            df.at[i, 'stop'] = stop
            df.at[i, 'tp'] = tp
            df.at[i, 'rrr'] = rrr_target

            for j in range(i + 1, min(i + 30, len(df))):
                price = df['close'].iloc[j]
                if price >= stop:
                    df.at[i, 'exit'] = price
                    df.at[i, 'pnl'] = entry - price
                    df.at[i, 'success'] = False
                    break
                elif price <= tp:
                    df.at[i, 'exit'] = price
                    df.at[i, 'pnl'] = entry - price
                    df.at[i, 'success'] = True
                    break

    result = df[df['signal'].notnull()][[
        'timestamp', 'signal', 'entry', 'stop', 'tp', 'exit', 'rrr', 'pnl', 'success'
    ]].reset_index(drop=True)

    return result



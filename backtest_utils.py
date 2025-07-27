import pandas as pd
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange

def backtest_strategy(df, rrr_target=2.5, min_adx=17):
    df = df.copy()
    df['ema_21'] = EMAIndicator(df['close'], window=21).ema_indicator()
    df['macd'] = MACD(df['close']).macd_diff()
    df['rsi'] = RSIIndicator(df['close']).rsi()
    df['adx'] = ADXIndicator(df['high'], df['low'], df['close']).adx()
    df['atr'] = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range()
    df['bb_upper'] = BollingerBands(df['close']).bollinger_hband()
    df['bb_lower'] = BollingerBands(df['close']).bollinger_lband()

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
        if df['signal'].iloc[i - 1] is not None:
            continue

        row = df.iloc[i]
        atr = row['atr']
        adx = row['adx']
        rsi = row['rsi']
        macd = row['macd']
        price = row['close']

        score = 0
        if 15 < rsi < 35 or 65 < rsi < 85: score += 1
        if macd > 0 or macd < 0: score += 1
        if adx >= min_adx: score += 1
        if row['close'] > row['ema_21']: score += 1
        if row['volume'] > df['volume'].rolling(10).mean().iloc[i] * 1.3: score += 1

        # תנאי LONG
        if (
            rsi < 30 and macd > 0 and price > row['ema_21'] and adx >= min_adx
        ):
            entry = price
            stop = entry - atr * 1.5
            tp = entry + (rrr_target * (entry - stop))
            df.at[i, 'signal'] = 'LONG'

        # תנאי SHORT
        elif (
            rsi > 70 and macd < 0 and price < row['ema_21'] and adx >= min_adx
        ):
            entry = price
            stop = entry + atr * 1.5
            tp = entry - (rrr_target * (stop - entry))
            df.at[i, 'signal'] = 'SHORT'
        else:
            continue

        df.at[i, 'entry'] = entry
        df.at[i, 'stop'] = stop
        df.at[i, 'tp'] = tp
        df.at[i, 'rrr'] = rrr_target
        df.at[i, 'quality_score'] = round(score / 5, 2)

        for j in range(i + 1, min(i + 30, len(df))):
            close_price = df['close'].iloc[j]
            if df.at[i, 'signal'] == 'LONG':
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
            else:  # SHORT
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
        'timestamp', 'signal', 'entry', 'stop', 'tp', 'exit', 'rrr', 'pnl', 'success', 'quality_score'
    ]].reset_index(drop=True)

    return result




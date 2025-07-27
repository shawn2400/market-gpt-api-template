from utils.quality_score import compute_quality_score

def scan_all_futures_live():
    results = []
    symbols = [s['symbol'] for s in client.futures_exchange_info()['symbols']
               if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT']

    for symbol in symbols:
        klines = get_klines(symbol)
        if len(klines) < 50:
            continue

        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'qav', 'trades', 'tb_base', 'tb_quote', 'ignore'
        ])
        df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)

        live_price = get_live_price(symbol)
        if not live_price:
            continue
        df.at[df.index[-1], 'close'] = live_price

        df = calculate_indicators(df)

        # בניית df_row לשימוש עם compute_quality_score
        row = df.iloc[-1]
        direction = 'LONG'  # לפי תנאי ניתוח טכני בסיסי, אתה יכול גם לחשב דינמית
        df_row = {
            "close": row['close'],
            "atr": row['ATR'],
            "macd": row['MACD'],
            "rsi": row['RSI'],
            "adx": row['ADX'],
            "volume": row['volume'],
            "volume_mean": df['volume'].iloc[:-1].mean(),
            "ema_21": row['EMA21'],
            "direction": direction
        }

        score = compute_quality_score(df_row)

        if score >= 4:
            results.append({
                'symbol': symbol,
                'price': live_price,
                'signal': direction,
                'EMA21': row['EMA21'],
                'EMA50': row['EMA50'],
                'RSI': row['RSI'],
                'MACD': row['MACD'],
                'ADX': row['ADX'],
                'ATR': row['ATR'],
                'volume': row['volume'],
                'volume_avg': df_row['volume_mean'],
                'quality_score': score
            })

        time.sleep(0.05)

    return results

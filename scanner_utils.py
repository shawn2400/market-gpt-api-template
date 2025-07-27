def scan_all_futures_live(budget_usd=100):
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

        # תנאי LONG:
        ema_cross = df['EMA21'].iloc[-2] < df['EMA50'].iloc[-2] and df['EMA21'].iloc[-1] > df['EMA50'].iloc[-1]
        macd_cross = df['MACD'].iloc[-2] < df['MACD_signal'].iloc[-2] and df['MACD'].iloc[-1] > df['MACD_signal'].iloc[-1]
        rsi_ok = 50 < df['RSI'].iloc[-1] < 70
        adx_ok = df['ADX'].iloc[-1] > 17
        volume_ok = is_volume_spike(df)

        if all([ema_cross, macd_cross, rsi_ok, adx_ok, volume_ok]):
            # הכנת df_row לפי הדרישות של compute_quality_score
            row = df.iloc[-1]
            direction = 'LONG'
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
                # חישוב SL/TP לפי ATR
                atr = row['ATR']
                stop_loss = round(live_price - 1.5 * atr, 4)
                take_profit = round(live_price + 3 * atr, 4)
                risk = live_price - stop_loss
                reward = take_profit - live_price
                rrr = round(reward / risk, 2) if risk > 0 else 0

                # מינוף חכם לפי תקציב
                qty = round((budget_usd * 1.0) / live_price, 3)

                results.append({
                    'symbol': symbol,
                    'price': live_price,
                    'signal': direction,
                    'EMA21': row['EMA21'],
                    'EMA50': row['EMA50'],
                    'RSI': row['RSI'],
                    'MACD': row['MACD'],
                    'ADX': row['ADX'],
                    'ATR': atr,
                    'volume': row['volume'],
                    'quality_score': score,
                    'entry': live_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'RRR': rrr,
                    'quantity': qty
                })

        time.sleep(0.05)

    # 🥇 מיון לפי Quality Score ו־RRR
    top = sorted(results, key=lambda x: (x['quality_score'], x['RRR']), reverse=True)[:10]
    return top















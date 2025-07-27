def scan_all_futures():
    symbols = get_futures_symbols()

    for symbol in symbols:
        df = fetch_klines(symbol)
        if df is None or df.empty:
            continue

        try:
            df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
            df['macd'] = ta.trend.MACD(df['close']).macd()
            df['ema21'] = ta.trend.EMAIndicator(df['close'], window=21).ema_indicator()
            df['adx'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close']).adx()
        except Exception as e:
            logging.warning(f"[scan] אינדיקטור נכשל עבור {symbol}: {e}")
            continue

        last = df.iloc[-1]
        prev = df.iloc[-2]

        if (
            last['rsi'] > 55 and
            last['macd'] > 0 and
            last['close'] > last['ema21'] and
            last['adx'] > 17 and
            last['volume'] > prev['volume'] * 1.3
        ):
            entry = round(last['close'], 4)
            stop = round(entry * 0.97, 4)
            tp = round(entry * 1.05, 4)
            leverage = 20
            budget = 100
            confidence = 90

            df['ema_21'] = df['ema21']
            df['volume_mean'] = df['volume'].rolling(window=20).mean()
            df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close']).average_true_range()
            df['direction'] = "LONG"
            quality = compute_quality_score(df.iloc[-1])

            if quality < 4:
                continue

            try:
                capital = auto_risk_allocation(entry, stop, budget)
                result = execute_trade_live(
                    symbol=symbol,
                    entry=entry,
                    stop=stop,
                    tp=tp,
                    direction="LONG",
                    leverage=leverage,
                    budget_usd=capital,
                    use_grid=True
                )

                save_trade(
                    symbol=symbol,
                    entry=entry,
                    stop=stop,
                    tp=tp,
                    direction="LONG",
                    leverage=leverage,
                    confidence=confidence,
                    quality_score=quality,
                    trade_type="GRID"
                )

                return {
                    "executed_trade": {
                        "symbol": symbol,
                        "entry": entry,
                        "stop": stop,
                        "tp": tp,
                        "leverage": leverage,
                        "direction": "LONG",
                        "confidence": confidence,
                        "quality_score": quality
                    }
                }

            except Exception as e:
                logging.error(f"[scan_all_futures] שגיאה בהפעלה ל־{symbol}: {e}")
                continue

    return {"executed_trade": None}











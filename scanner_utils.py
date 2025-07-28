def scan_all_futures_live(budget_usd=100):
    try:
        print("🚀 התחלת סריקה חיה")
        symbols = [
            s['symbol']
            for s in client.futures_exchange_info()['symbols']
            if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT'
        ]
    except Exception as e:
        print(f"[!] שגיאה בקבלת רשימת סמלים: {e}")
        return []

    results = []

    for i, symbol in enumerate(symbols[:20]):  # הוגבל ל־20 סמלים בלבד לצורך בדיקה
        try:
            print(f"[{i}] 🔍 בודק {symbol}")
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

            indicators = compute_indicators(df)
            signal = indicators['signal']
            df = indicators['df']

            score = compute_quality_score(df)

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























# scanner_utils.py
import time
import pandas as pd
from binance.client import Client
from utils.binance_client import client
from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score

def scan_all_futures_live(budget_usd=100):
    symbols = [s['symbol'] for s in client.futures_exchange_info()['symbols'] if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT']
    results = []

    for symbol in symbols[:300]:
        try:
            klines = client.futures_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_15MINUTE, limit=100)
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
            print(f"שגיאה ב־{symbol}: {e}")
            continue

    sorted_results = sorted(results, key=lambda x: x['quality_score'], reverse=True)
    return sorted_results





















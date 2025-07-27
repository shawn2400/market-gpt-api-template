import time
import pandas as pd
from utils.binance_client import client
from utils.indicators import calculate_indicators, is_volume_spike
from utils.quality_score import compute_quality_score
from utils.get_live_price import get_live_price
from utils.get_klines import get_klines
from utils.quantity_utils import calculate_quantity, auto_risk_allocation, generate_grid_levels


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

        row = df.iloc[-1]
        base_row = {
            "close": row['close'],
            "atr": row['ATR'],
            "macd": row['MACD'],
            "rsi": row['RSI'],
            "adx": row['ADX'],
            "volume": row['volume'],
            "volume_mean": df['volume'].iloc[:-1].mean(),
            "ema_21": row['EMA21']
        }

        setups = []

        # תנאי LONG
        if (df['EMA21'].iloc[-2] < df['EMA50'].iloc[-2] and df['EMA21'].iloc[-1] > df['EMA50'].iloc[-1] and
            df['MACD'].iloc[-2] < df['MACD_signal'].iloc[-2] and df['MACD'].iloc[-1] > df['MACD_signal'].iloc[-1] and
            50 < df['RSI'].iloc[-1] < 70 and df['ADX'].iloc[-1] > 17 and is_volume_spike(df)):

            df_row = {**base_row, "direction": "LONG"}
            setups.append(df_row)

        # תנאי SHORT
        if (df['EMA21'].iloc[-2] > df['EMA50'].iloc[-2] and df['EMA21'].iloc[-1] < df['EMA50'].iloc[-1] and
            df['MACD'].iloc[-2] > df['MACD_signal'].iloc[-2] and df['MACD'].iloc[-1] < df['MACD_signal'].iloc[-1] and
            30 < df['RSI'].iloc[-1] < 50 and df['ADX'].iloc[-1] > 17 and is_volume_spike(df)):

            df_row = {**base_row, "direction": "SHORT"}
            setups.append(df_row)

        for df_row in setups:
            score = compute_quality_score(df_row) * 10  # הפיכת score ל־0–100
            if score >= 86:
                atr = row['ATR']
                direction = df_row['direction']

                if direction == 'LONG':
                    stop_loss = round(live_price - 1.5 * atr, 4)
                    take_profit = round(live_price + 3 * atr, 4)
                else:
                    stop_loss = round(live_price + 1.5 * atr, 4)
                    take_profit = round(live_price - 3 * atr, 4)

                risk = abs(live_price - stop_loss)
                reward = abs(take_profit - live_price)
                rrr = round(reward / risk, 2) if risk > 0 else 0

                qty = calculate_quantity(budget_usd, live_price, 1)
                capital = auto_risk_allocation(live_price, stop_loss, budget_usd)
                grid = generate_grid_levels(live_price, take_profit)

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
                    'quality_score': round(score, 2),
                    'entry': live_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'RRR': rrr,
                    'quantity': qty,
                    'risk_capital': round(capital, 2),
                    'grid_levels': grid,
                    'expected_profit': round(reward * qty, 2),
                    'expected_loss': round(risk * qty, 2)
                })

        time.sleep(0.05)

    top = sorted(results, key=lambda x: (x['quality_score'], x['RRR']), reverse=True)[:10]
    return top

















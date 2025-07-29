# market_scan_utils.py

import logging
import pandas as pd
from utils.binance_client import client
from utils.indicators import compute_indicators
from utils.get_live_price import get_live_price
from utils.sl_tp_utils import calc_sl_tp_by_atr

### 1. בדיקת סטטוס API
def check_binance_status():
    try:
        client.futures_ping()
        return True
    except Exception as e:
        logging.warning(f"Binance API לא מגיב: {e}")
        return False

### 2. שליפת כל הסימבולים הנתמכים לפי USDT בלבד
def get_futures_symbols():
    try:
        info = client.futures_exchange_info()
        symbols = [x['symbol'] for x in info['symbols'] if x['quoteAsset'] == 'USDT']
        return symbols
    except Exception as e:
        logging.error(f"[!] שגיאה בשליפת סימבולים: {e}")
        return []

### 3. שליפת bid/ask/high/low לכל מטבע
def get_bid_ask_high_low(symbol: str):
    try:
        orderbook = client.get_orderbook_ticker(symbol=symbol)
        stats = client.get_ticker_24hr(symbol=symbol)
        return {
            "bid": float(orderbook["bidPrice"]),
            "ask": float(orderbook["askPrice"]),
            "high": float(stats["highPrice"]),
            "low": float(stats["lowPrice"]),
        }
    except Exception as e:
        logging.error(f"[!] bid/ask/high/low error for {symbol}: {e}")
        return {}

### 4. סריקת פיוצ’רס חיה לכל השוק (כולל אינדיקטורים)
def scan_all_futures_symbols(limit=100):
    try:
        all_tickers = client.futures_ticker_price()
        symbols = [x['symbol'] for x in all_tickers if x['symbol'].endswith('USDT')]
        prices = {x['symbol']: float(x['price']) for x in all_tickers}
        symbols = symbols[:limit]
        result = []
        for symbol in symbols:
            klines = client.futures_klines(symbol=symbol, interval='5m', limit=100)
            df = pd.DataFrame(klines, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore'
            ])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            df = compute_indicators(df)
            last = df.iloc[-1]
            result.append({
                "symbol": symbol,
                "price": prices[symbol],
                "rsi": last['rsi'],
                "adx": last['adx'],
                "macd": last['macd'],
                "volume": last['volume'],
                "ema_21": last['ema_21'],
                "ema_50": last['ema_50'],
                "quality_score": last.get('tech_score', 0)
            })
        return result
    except Exception as e:
        logging.error(f"[!] SCAN שגיאה: {e}")
        return []

### 5. שליפת סימבול הכי איכותי (best trade)
def get_best_trade_symbol(limit=50, min_score=2):
    data = scan_all_futures_symbols(limit=limit)
    if not data:
        return None
    filtered = [x for x in data if x["quality_score"] >= min_score]
    if not filtered:
        return None
    best = max(filtered, key=lambda x: x["quality_score"])
    return best

### 6. שילוב LIVE PRICE עם חישוב SL/TP לפי ATR
def get_trade_levels(symbol, direction="long"):
    price = get_live_price(symbol, is_futures=True)
    klines = client.futures_klines(symbol=symbol, interval='5m', limit=100)
    df = pd.DataFrame(klines, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    df = compute_indicators(df)
    last = df.iloc[-1]
    sl, tp = calc_sl_tp_by_atr(last['close'], last['atr'], direction=direction)
    return {"price": price, "sl": sl, "tp": tp}

### 7. הפעלה אסינכרונית (async) לסריקות מהירות
import asyncio

async def scan_async(symbols):
    loop = asyncio.get_event_loop()
    results = await asyncio.gather(*[loop.run_in_executor(None, get_live_price, s, True) for s in symbols])
    return dict(zip(symbols, results))

### 8. דוגמת זרימת עבודה מלאה – מציאת טרייד מוכן
def auto_scan_and_trade(min_rsi=35, min_adx=20, limit=100):
    scan_results = scan_all_futures_symbols(limit=limit)
    signals = []
    for coin in scan_results:
        if coin['rsi'] < min_rsi and coin['adx'] > min_adx:
            signals.append(coin)
            print(f"ENTRY: {coin['symbol']} @ {coin['price']} (RSI={coin['rsi']:.2f}, ADX={coin['adx']:.2f}, Score={coin['quality_score']})")
    return signals

# דוגמה להפעלה מהירה:
if __name__ == "__main__":
    if not check_binance_status():
        print("Binance API לא פעיל כרגע.")
    else:
        best = get_best_trade_symbol(limit=30, min_score=3)
        if best:
            print(f"Best trade: {best['symbol']} | Price: {best['price']} | Score: {best['quality_score']}")
        trades = auto_scan_and_trade()




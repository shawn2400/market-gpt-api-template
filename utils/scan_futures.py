# utils/market_scan_utils.py

import logging
import pandas as pd
from utils.binance_client import client
from utils.indicators import compute_indicators

def check_binance_status():
    """בדיקת זמינות Binance API"""
    try:
        client.futures_ping()
        return True
    except Exception as e:
        logging.warning(f"Binance API לא מגיב: {e}")
        return False

def get_futures_symbols():
    """שליפת כל סימבולי USDT הנתמכים בפיוצ'רס"""
    try:
        info = client.futures_exchange_info()
        return [x['symbol'] for x in info['symbols'] if x['quoteAsset'] == 'USDT']
    except Exception as e:
        logging.error(f"[!] שגיאה בשליפת סימבולים: {e}")
        return []

def get_bid_ask_high_low(symbol: str):
    """שליפת bid/ask/high/low"""
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

def scan_all_futures_symbols(limit=100, interval='5m'):
    """סריקת פיוצ’רס חיה עם אינדיקטורים (sync)"""
    try:
        all_tickers = client.futures_ticker_price()
        symbols = [x['symbol'] for x in all_tickers if x['symbol'].endswith('USDT')]
        prices = {x['symbol']: float(x['price']) for x in all_tickers}
        symbols = symbols[:limit]
        result = []
        for symbol in symbols:
            try:
                klines = client.futures_klines(symbol=symbol, interval=interval, limit=100)
                df = pd.DataFrame(klines, columns=[
                    'open_time', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_asset_volume', 'number_of_trades',
                    'taker_buy_base', 'taker_buy_quote', 'ignore'
                ])
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                df = compute_indicators(df)
                last = df.iloc[-1]

                # לייבא את הפונקציה רק כאן למניעת תלות מעגלית
                from utils.sl_tp_utils import calculate_sl_tp

                sl, tp = calculate_sl_tp(last['close'], direction='long', atr=last.get('atr', None))

                result.append({
                    "symbol": symbol,
                    "price": prices.get(symbol),
                    "rsi": last['rsi'],
                    "adx": last['adx'],
                    "macd": last['macd'],
                    "volume": last['volume'],
                    "ema_21": last['ema_21'],
                    "ema_50": last['ema_50'],
                    "quality_score": last.get('tech_score', 0),
                    "sl": sl,
                    "tp": tp
                })
            except Exception as e:
                logging.warning(f"[!] Symbol {symbol} error: {e}")
        return result
    except Exception as e:
        logging.error(f"[!] SCAN שגיאה: {e}")
        return []

def get_best_trade_symbol(limit=50, min_score=2):
    """הסימבול הכי איכותי לשוק"""
    data = scan_all_futures_symbols(limit=limit)
    if not data:
        return None
    filtered = [x for x in data if x["quality_score"] >= min_score]
    if not filtered:
        return None
    best = max(filtered, key=lambda x: x["quality_score"])
    return best

def get_trade_levels(symbol, direction="long", interval="5m"):
    """מחיר נוכחי + SL/TP לפי ATR"""
    from utils.get_live_price import get_live_price  # לייט-אימפורט! (למניעת circular)
    from utils.sl_tp_utils import calculate_sl_tp

    price = get_live_price(symbol, is_futures=True)
    klines = client.futures_klines(symbol=symbol, interval=interval, limit=100)
    df = pd.DataFrame(klines, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    df = compute_indicators(df)
    last = df.iloc[-1]
    sl, tp = calculate_sl_tp(last['close'], last['atr'], direction=direction)
    return {"price": price, "sl": sl, "tp": tp}

# דוגמת זרימת עבודה מלאה – מציאת טרייד מוכן
def auto_scan_and_trade(min_rsi=35, min_adx=20, limit=100):
    scan_results = scan_all_futures_symbols(limit=limit)
    signals = []
    for coin in scan_results:
        if coin['rsi'] < min_rsi and coin['adx'] > min_adx:
            signals.append(coin)
            print(f"ENTRY: {coin['symbol']} @ {coin['price']} (RSI={coin['rsi']:.2f}, ADX={coin['adx']:.2f}, Score={coin['quality_score']})")
    return signals

# הפעלה סינכרונית בלבד (אין ייבוא מיותר, אין תלות צולבת)
if __name__ == "__main__":
    if not check_binance_status():
        print("Binance API לא פעיל כרגע.")
    else:
        best = get_best_trade_symbol(limit=30, min_score=3)
        if best:
            print(f"Best trade: {best['symbol']} | Price: {best['price']} | Score: {best['quality_score']}")
        trades = auto_scan_and_trade()











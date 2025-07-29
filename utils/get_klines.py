# utils/get_klines.py

from utils.binance_client import client
import pandas as pd

def get_klines(
    symbol: str,
    interval: str = '15m',
    limit: int = 100,
    market_type: str = "futures",  # "futures" / "spot" / "grid"
    grid_base_type: str = "futures",  # relevant if market_type == "grid"
    start_time: int = None,
    end_time: int = None,
    is_futures: bool = None  # להוסיף לשם תאימות אחורה
) -> pd.DataFrame:
    """
    מחזיר DataFrame של נתוני נרות (Klines) מ־Binance (Futures/Spot/לגריד לפי הגדרת השוק).

    Args:
        symbol (str): לדוג' 'BTCUSDT'
        interval (str): לדוג' '1m', '15m', '1h'
        limit (int): מקסימום 1500
        market_type (str): "futures" / "spot" / "grid"
        grid_base_type (str): אם market_type=="grid", בוחר מקור ('futures'/'spot')
        start_time (int): אופציונלי (ms)
        end_time (int): אופציונלי (ms)
        is_futures (bool): פרמטר ישן, אם קיים - מגדיר את market_type בהתאם

    Returns:
        pd.DataFrame: טבלה סטנדרטית עם עמודות timestamp, open, high, low, close, volume
    """
    if is_futures is not None:
        market_type = "futures" if is_futures else "spot"

    if not client:
        print("⚠️ Binance client לא מחובר.")
        return pd.DataFrame()

    mt = market_type
    if market_type == "grid":
        mt = grid_base_type if grid_base_type in ("futures", "spot") else "futures"

    try:
        if mt == "futures":
            raw = client.futures_klines(
                symbol=symbol,
                interval=interval,
                limit=limit,
                startTime=start_time,
                endTime=end_time
            )
        elif mt == "spot":
            raw = client.get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit,
                startTime=start_time,
                endTime=end_time
            )
        else:
            print(f"[!] סוג שוק לא נתמך: {mt}")
            return pd.DataFrame()

        df = pd.DataFrame(raw, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
        ])

        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)

        return df

    except Exception as e:
        print(f"[!] שגיאה בשליפת Klines עבור {symbol}: {e}")
        return pd.DataFrame()







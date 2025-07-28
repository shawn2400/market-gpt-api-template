# services/auto_executor.py

import asyncio
from scanner_utils import scan_all_futures
from trade_executor import execute_trade_live
from utils.quantity_utils import calculate_quantity

DEFAULT_BUDGET_USD = 100  # ניתן לשנות לפי צורך
DEFAULT_LEVERAGE = 10

async def start_auto_executor():
    """
    סורק ומבצע טריידים אוטומטית ברקע לפי תנאים מחמירים. רץ בלולאה כל X זמן.
    """
    print("🚀 Auto Executor התחיל לעבוד ברקע...")

    while True:
        try:
            trades = await scan_all_futures()
            print(f"🔍 נמצאו {len(trades)} טריידים פוטנציאליים")

            for trade in trades:
                symbol = trade['symbol']
                direction = trade['direction']
                entry = trade['entry']
                stop = trade['stop']
                tp = trade['tp']

                quantity = calculate_quantity(
                    symbol=symbol,
                    price=entry,
                    leverage=DEFAULT_LEVERAGE,
                    budget=DEFAULT_BUDGET_USD
                )

                result = await execute_trade_live(
                    symbol=symbol,
                    entry=entry,
                    stop=stop,
                    tp=tp,
                    direction=direction,
                    leverage=DEFAULT_LEVERAGE,
                    budget_usd=DEFAULT_BUDGET_USD,
                    use_grid=False,
                    use_trailing=False,
                    user_id="auto"
                )

                print(f"✅ טרייד בוצע: {symbol} | {direction} | Qty: {quantity}")

        except Exception as e:
            print(f"❌ שגיאה ב־Auto Executor: {e}")

        await asyncio.sleep(60 * 3)  # המתנה 3 דקות לפני הרצה חוזרת

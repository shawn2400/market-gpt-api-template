import asyncio
import os
from dotenv import load_dotenv
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_executor import execute_trade_live
from utils.trade_manager import manage_open_trades
from utils.watchlist_utils import load_watchlist
from utils.config import (
    AUTO_RUN,
    SCAN_INTERVAL,
    MIN_QUALITY_SCORE,
    MAX_TRADE_BUDGET,
    EXECUTE_TRADES,
    ALLOW_MANAGE_OPEN_TRADES,
)

load_dotenv()

# ניהול תקציב ריאלי לפי טריידים פתוחים
from utils.trade_storage import load_open_trades

def get_total_allocated_budget():
    open_trades = load_open_trades()
    return sum(t.get("budget", 0) for t in open_trades)

async def auto_executor():
    if not AUTO_RUN:
        print("⚠️ AUTO_RUN כבוי בקובץ הסביבה.")
        return

    while True:
        try:
            print("🚀 מריץ סריקה חכמה...")
            watchlist = load_watchlist()
            results = await multi_tf_scan_with_ai(watchlist)

            for trade in results:
                symbol = trade["symbol"]
                score = trade.get("score", 0)
                budget = trade.get("budget", MAX_TRADE_BUDGET)
                direction = trade.get("direction", "LONG")

                allocated = get_total_allocated_budget()
                if allocated + budget > MAX_TRADE_BUDGET:
                    print(f"⛔ אין מספיק תקציב לטרייד ב־{symbol} | בשימוש: {allocated}$")
                    continue

                if score < MIN_QUALITY_SCORE:
                    print(f"⛔ טרייד ב־{symbol} לא עבר את הסף ({score} < {MIN_QUALITY_SCORE})")
                    continue

                if EXECUTE_TRADES:
                    print(f"📈 פותח טרייד חכם ב־{symbol} עם תקציב {budget}$")
                    await execute_trade_live(symbol, direction, budget)
                else:
                    print(f"🧪 DRY RUN | הדמיית טרייד ב־{symbol}")

            # ניהול חי מלא אם מופעל
            if ALLOW_MANAGE_OPEN_TRADES:
                await manage_open_trades()

        except Exception as e:
            print(f"❌ שגיאה במנהל האוטומטי: {e}")

        print(f"⌛ ממתין {SCAN_INTERVAL} שניות עד לסריקה הבאה...\n")
        await asyncio.sleep(SCAN_INTERVAL)

# להפעלה חיצונית
if __name__ == "__main__":
    asyncio.run(auto_executor())




















































































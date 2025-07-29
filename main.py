import asyncio
import os
from scanner_utils import scan_all_futures
from trade_executor import execute_trade_live
from dotenv import load_dotenv

load_dotenv()

# פונקציה ראשית שמבצעת סריקה ואוטומציה של טריידים
async def start_auto_executor(delay: int = 60, min_quality: int = 6, max_budget: float = 100):
    print("🔄 Auto Executor started with delay =", delay, "seconds")

    while True:
        try:
            print("📡 Scanning market for high quality trades...")
            trades = await scan_all_futures()

            # סינון לפי ציון איכות בלבד
            high_quality_trades = [t for t in trades if t.get("quality_score", 0) >= min_quality]
            print(f"🎯 Found {len(high_quality_trades)} high quality trades")

            for trade in high_quality_trades:
                try:
                    print(f"🚀 Executing trade: {trade['symbol']} ({trade['direction']})")
                    await execute_trade_live(
                        symbol=trade['symbol'],
                        entry=trade['entry'],
                        stop=trade['stop'],
                        tp=trade['tp'],
                        direction=trade['direction'],
                        leverage=trade.get('leverage', 10),
                        budget_usd=max_budget,
                        use_grid=trade.get('use_grid', False),
                        use_trailing=trade.get('use_trailing', False),
                        user_id="auto"
                    )
                except Exception as trade_error:
                    print(f"❌ Trade execution failed: {trade_error}")

        except Exception as e:
            print(f"⚠️ Auto executor error: {e}")

        print(f"⏳ Waiting {delay} seconds before next scan...\n")
        await asyncio.sleep(delay)
































































































































































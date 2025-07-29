import asyncio
import os
import traceback
from dotenv import load_dotenv

load_dotenv()

AUTO_USER_ID = "auto"
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", 10))

async def start_auto_executor(delay: int = 30, min_quality: int = 6, max_budget: float = 100):
    print("[AUTO_EXECUTOR] 🔁 Auto executor started with delay:", delay)
    
    while True:
        try:
            print("[AUTO_EXECUTOR] 🔍 Scanning for trade opportunities...")

            # 💤 Lazy import – רק בעת שימוש
            from scanner_utils import scan_all_futures
            from trade_executor import execute_trade_live

            results = await scan_all_futures()
            filtered = [r for r in results if r.get("quality_score", 0) >= min_quality]

            if not filtered:
                print(f"[AUTO_EXECUTOR] ❌ No trades found with quality >= {min_quality}")
            else:
                best = max(filtered, key=lambda x: x["quality_score"])
                print(f"[AUTO_EXECUTOR] ✅ Found high quality trade: {best['symbol']} Score: {best['quality_score']}")

                # הרצת טרייד בפועל
                response = await execute_trade_live(
                    symbol=best['symbol'],
                    entry=best['entry_price'],
                    stop=best['sl'],
                    tp=best['tp'],
                    direction=best['direction'],
                    leverage=best.get('leverage', DEFAULT_LEVERAGE),
                    budget_usd=max_budget,
                    use_grid=best.get("use_grid", False),
                    use_trailing=best.get("use_trailing", False),
                    user_id=AUTO_USER_ID
                )
                print("[AUTO_EXECUTOR] 🚀 Trade executed:", response)

        except Exception as e:
            print("[AUTO_EXECUTOR] ❗ Error:", str(e))
            traceback.print_exc()

        await asyncio.sleep(delay)





import asyncio
import logging
from utils.scanner_utils import scan_all
from utils.trade_executor import execute_trade_live

async def start_auto_executor(delay=60, min_quality=6, max_budget=100):
    while True:
        try:
            logging.info(f"[AUTO_EXECUTOR] מתחיל סריקה חיה... (min_quality={min_quality})")
            trades = await scan_all(min_quality=min_quality)

            if not trades:
                logging.info("[AUTO_EXECUTOR] לא נמצאו טריידים מתאימים")
                await asyncio.sleep(delay)
                continue

            trade = trades[0]
            logging.info(f"[AUTO_EXECUTOR] מבצע טרייד חי על {trade['symbol']} ({trade['direction']})")

            await asyncio.to_thread(
                execute_trade_live,
                symbol=trade["symbol"],
                entry=trade.get("close", None),
                stop=trade.get("stop", None),
                tp=trade.get("tp", None),
                direction=trade["direction"],
                leverage=10,
                budget_usd=max_budget,
                use_grid=False,
                use_trailing=True
            )

        except Exception as e:
            logging.error(f"[AUTO_EXECUTOR] שגיאה: {e}")

        await asyncio.sleep(delay)
















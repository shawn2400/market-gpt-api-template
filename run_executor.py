# run_executor.py
import asyncio, argparse, logging, os
from dotenv import load_dotenv

from utils.scanner_utils import scan_all
from utils.trade_executor import execute_trade_live
from utils.ws_fallback import get_price_smart
from utils.ai_analysis import predict_optimal_sl_tp

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MAX_OPEN_TRADES = 4

async def run_executor(debug=False, once=False, delay=60, min_quality=6, max_budget=100.0, market_type="futures"):
    while True:
        trades = await scan_all(symbols=[], market_type=market_type, interval="15m", min_quality=min_quality, top=1)

        if trades:
            trade = trades[0]
            logging.info(f"🎯 טרייד נבחר: {trade['symbol']} | איכות: {trade.get('quality_score')}")
            price = await get_price_smart(trade["symbol"])
            if not price:
                logging.warning("⚠️ מחיר חי לא זמין – דילוג")
            else:
                sl, tp = await predict_optimal_sl_tp(
                    symbol=trade["symbol"], direction=trade["direction"],
                    entry_price=float(price), atr=None
                )
                if not debug:
                    resp = await execute_trade_live(
                        symbol=trade["symbol"], entry=float(price), stop=sl, tp=tp,
                        direction=trade["direction"], leverage=20,
                        budget_usd=max_budget, market_type=market_type
                    )
                    logging.info(f"✍️ execute_trade_live → {resp.get('status')}")
                else:
                    logging.info("[DEBUG] מצב בדיקה – לא נשלחה הזמנה ל־Binance")
        else:
            logging.info("⚠️ לא נמצא טרייד איכותי.")

        if once:
            break
        await asyncio.sleep(delay)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="הרצה חיה של AlgoGPT Auto Executor")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--delay", type=int, default=60)
    parser.add_argument("--min_quality", type=int, default=6)
    parser.add_argument("--budget", type=float, default=100)
    parser.add_argument("--market_type", type=str, default="futures")
    args = parser.parse_args()

    asyncio.run(run_executor(
        debug=args.debug, once=args.once, delay=args.delay,
        min_quality=args.min_quality, max_budget=args.budget, market_type=args.market_type
    ))










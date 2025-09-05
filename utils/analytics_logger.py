# ✅ analytics_logger.py — תיעוד פעולות Approve/Reject
import logging
from datetime import datetime
from pathlib import Path

LOG_PATH = Path("logs/telegram_actions.log")
logger = logging.getLogger("analytics_logger")
logger.setLevel(logging.INFO)

handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

def log_action(action: str, trade_id: str, user: str, symbol: str, extra: str = ""):
    msg = f"{action.upper()} | {trade_id} | {user} | {symbol} | {extra}"
    logger.info(msg)

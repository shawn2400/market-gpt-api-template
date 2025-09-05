# תפקיד: קריאות מ־executors → שיגור Telegram חכם
# מופעל בעת TP/SL/BE ומעביר ל־telegram_notifier

from __future__ import annotations
import logging
from typing import Optional

from utils.telegram_notifier import notify_tp_hit, notify_sl_hit, notify_be_moved

logger = logging.getLogger("algogpt.executors")

def on_tp_hit(symbol: str, tp_price: float, tp_level: int):
    try:
        notify_tp_hit(symbol=symbol, price=tp_price, tp_level=tp_level)
    except Exception as e:
        logger.warning("[telegram] failed to notify TP hit: %s", e)

def on_sl_hit(symbol: str, sl_price: float):
    try:
        notify_sl_hit(symbol=symbol, price=sl_price)
    except Exception as e:
        logger.warning("[telegram] failed to notify SL hit: %s", e)

def on_be_moved(symbol: str, old_sl: float, new_sl: float):
    try:
        notify_be_moved(symbol=symbol, old_sl=old_sl, new_sl=new_sl)
    except Exception as e:
        logger.warning("[telegram] failed to notify BE move: %s", e)

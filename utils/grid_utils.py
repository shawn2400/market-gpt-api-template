# utils/grid_utils.py

import logging
import math
import time
from utils.binance_client import client
from utils.get_live_price import get_live_price

def round_step(quantity, step):
    """ עיגול כמות לפי stepSize של סימבול """
    return math.floor(quantity / step) * step

def get_symbol_step(symbol, futures=False):
    info = client.futures_exchange_info() if futures else client.get_exchange_info()
    for s in info['symbols']:
        if s['symbol'] == symbol:
            for f in s['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    return float(f['stepSize'])
    return 0.01

def create_grid_levels(price, grid_size, grid_count, grid_pct=0.5, direction="BOTH"):
    """ מחזיר רשימת רמות מחיר לגריד דו־צדדי """
    levels = []
    for i in range(1, grid_count + 1):
        up = price * (1 + grid_pct / 100 * i)
        down = price * (1 - grid_pct / 100 * i)
        if direction in ("BOTH", "SELL"):
            levels.append(round(up, grid_size))
        if direction in ("BOTH", "BUY"):
            levels.append(round(down, grid_size))
    return sorted(list(set(levels)))

def place_limit_order_with_sl_tp(symbol, side, price, quantity, futures=True, leverage=1, tp_pct=1, sl_pct=1):
    """
    פותח פקודת LIMIT + SL/TP אוטומטיים בכל מקרה, אי אפשר לבטל!
    """
    results = {}
    try:
        if futures:
            # פקודת Limit
            order = client.futures_create_order(
                symbol=symbol,
                side=side,
                type="LIMIT",
                price=round(price, 4),
                quantity=quantity,
                timeInForce="GTC"
            )
            results['order'] = order

            # SL/TP Market ב־Futures: opposite side, STOP_MARKET ו־TAKE_PROFIT_MARKET
            sl_price = price * (1 - sl_pct / 100) if side == "BUY" else price * (1 + sl_pct / 100)
            tp_price = price * (1 + tp_pct / 100) if side == "BUY" else price * (1 - tp_pct / 100)
            # Stop Loss
            sl = client.futures_create_order(
                symbol=symbol,
                side="SELL" if side == "BUY" else "BUY",
                type="STOP_MARKET",
                stopPrice=round(sl_price, 4),
                closePosition=False,
                quantity=quantity,
                timeInForce="GTC"
            )
            # Take Profit
            tp = client.futures_create_order(
                symbol=symbol,
                side="SELL" if side == "BUY" else "BUY",
                type="TAKE_PROFIT_MARKET",
                stopPrice=round(tp_price, 4),
                closePosition=False,
                quantity=quantity,
                timeInForce="GTC"
            )
            results['sl'] = sl
            results['tp'] = tp

        else:
            # SPOT — פקודת OCO (LIMIT+TP+SL באותה הפקודה)
            sl_price = price * (1 - sl_pct / 100) if side == "BUY" else price * (1 + sl_pct / 100)
            tp_price = price * (1 + tp_pct / 100) if side == "BUY" else price * (1 - tp_pct / 100)
            oco = client.create_oco_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=round(price, 4),
                stopPrice=round(sl_price, 4),
                stopLimitPrice=round(sl_price, 4),
                limitPrice=round(tp_price, 4),
                timeInForce="GTC"
            )
            results['oco'] = oco

    except Exception as e:
        logging.error(f"גריד | {symbol} | {side}@{price}: {e}")
        results['error'] = str(e)
    return results

def execute_grid(symbol, budget=100, grid_count=6, grid_pct=0.5, leverage=1, futures=True, direction="BOTH", tp_pct=1, sl_pct=1):
    """
    פותח גריד (Futures/Spot) דו־צדדי — עם TP/SL אוטומטיים לכל רמה (חובה).
    """
    price = get_live_price(symbol, is_futures=futures)
    if not price:
        raise RuntimeError("⚠️ לא ניתן לקבל מחיר חי מה־API")
    step = get_symbol_step(symbol, futures=futures)
    quantity = round_step((budget * leverage / price) / grid_count, step)
    if quantity <= 0:
        raise RuntimeError("כמות לא חוקית לגריד (יתכן שתקציב קטן/stepSize בעייתי)")

    levels = create_grid_levels(price, grid_size=4, grid_count=grid_count, grid_pct=grid_pct, direction=direction)
    open_orders = []

    for lvl in levels:
        side = "BUY" if lvl < price else "SELL"
        res = place_limit_order_with_sl_tp(
            symbol, side, lvl, quantity, futures=futures, leverage=leverage,
            tp_pct=tp_pct, sl_pct=sl_pct  # חובה תמיד!
        )
        open_orders.append({
            "symbol": symbol, "side": side, "price": lvl, "quantity": quantity, "result": res
        })

    return open_orders

# דוגמה להפעלה:
if __name__ == "__main__":
    # פיוצ'רס — גריד דו־צדדי 8 רמות, עם TP/SL 1% (חובה בכל רמה!)
    open_orders = execute_grid(
        "BTCUSDT", budget=100, grid_count=8, grid_pct=0.5,
        leverage=5, futures=True, direction="BOTH", tp_pct=1, sl_pct=1
    )
    print("Grid orders:", open_orders)


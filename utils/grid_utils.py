# utils/grid_utils.py

import logging
import math
import time
from utils.binance_client import client
from utils.get_live_price import get_live_price

def round_step(value, step):
    """ מעגל value כלפי מטה ל־stepSize החוקי """
    return math.floor(value / step) * step

def get_symbol_step(symbol, futures=False):
    """ מחזיר את ה־stepSize החוקי של כמות/מחיר """
    info = client.futures_exchange_info() if futures else client.get_exchange_info()
    for s in info['symbols']:
        if s['symbol'] == symbol:
            for f in s['filters']:
                if f['filterType'] == 'PRICE_FILTER':
                    price_step = float(f['tickSize'])
                if f['filterType'] == 'LOT_SIZE':
                    qty_step = float(f['stepSize'])
            return price_step if futures else qty_step  # עבור Futures זה תקף לשניהם
    return 0.01

def create_grid_levels(price, step, grid_count, grid_pct=0.5, direction="BOTH"):
    """ יוצר רמות גריד מעוגלות לפי step החוקי """
    levels = []
    for i in range(1, grid_count + 1):
        up = round_step(price * (1 + grid_pct / 100 * i), step)
        down = round_step(price * (1 - grid_pct / 100 * i), step)
        if direction in ("BOTH", "SELL"):
            levels.append(up)
        if direction in ("BOTH", "BUY"):
            levels.append(down)
    # מנקה כפילויות, ממיין
    return sorted(set(levels))

def place_limit_order_with_sl_tp(symbol, side, price, quantity, futures=True, leverage=1, tp_pct=1, sl_pct=1):
    results = {}
    try:
        if futures:
            # Limit
            order = client.futures_create_order(
                symbol=symbol,
                side=side,
                type="LIMIT",
                price=round(price, 4),
                quantity=quantity,
                timeInForce="GTC"
            )
            results['order'] = order
            # SL
            sl_price = round(price * (1 - sl_pct / 100), 4) if side == "BUY" else round(price * (1 + sl_pct / 100), 4)
            tp_price = round(price * (1 + tp_pct / 100), 4) if side == "BUY" else round(price * (1 - tp_pct / 100), 4)
            sl = client.futures_create_order(
                symbol=symbol,
                side="SELL" if side == "BUY" else "BUY",
                type="STOP_MARKET",
                stopPrice=sl_price,
                closePosition=False,
                quantity=quantity,
                timeInForce="GTC"
            )
            tp = client.futures_create_order(
                symbol=symbol,
                side="SELL" if side == "BUY" else "BUY",
                type="TAKE_PROFIT_MARKET",
                stopPrice=tp_price,
                closePosition=False,
                quantity=quantity,
                timeInForce="GTC"
            )
            results['sl'] = sl
            results['tp'] = tp
        else:
            # SPOT OCO
            sl_price = round(price * (1 - sl_pct / 100), 4) if side == "BUY" else round(price * (1 + sl_pct / 100), 4)
            tp_price = round(price * (1 + tp_pct / 100), 4) if side == "BUY" else round(price * (1 - tp_pct / 100), 4)
            oco = client.create_oco_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=round(price, 4),
                stopPrice=sl_price,
                stopLimitPrice=sl_price,
                limitPrice=tp_price,
                timeInForce="GTC"
            )
            results['oco'] = oco
    except Exception as e:
        logging.error(f"גריד | {symbol} | {side}@{price}: {e}")
        results['error'] = str(e)
    return results

def execute_grid(symbol, budget=100, grid_count=6, grid_pct=0.5, leverage=1, futures=True, direction="BOTH", tp_pct=1, sl_pct=1):
    """
    פותח גריד (Futures/Spot) דו־צדדי — עם TP/SL אוטומטיים לכל רמה.
    """
    price = get_live_price(symbol, is_futures=futures)
    if not price:
        raise RuntimeError("⚠️ לא ניתן לקבל מחיר חי מה־API")
    step = get_symbol_step(symbol, futures=futures)
    quantity = round_step((budget * leverage / price) / grid_count, step)
    if quantity <= 0:
        raise RuntimeError("כמות לא חוקית לגריד (יתכן שתקציב קטן/stepSize בעייתי)")

    levels = create_grid_levels(price, step, grid_count, grid_pct=grid_pct, direction=direction)
    open_orders = []
    for lvl in levels:
        side = "BUY" if lvl < price else "SELL"
        res = place_limit_order_with_sl_tp(
            symbol, side, lvl, quantity, futures=futures, leverage=leverage,
            tp_pct=tp_pct, sl_pct=sl_pct
        )
        open_orders.append({
            "symbol": symbol, "side": side, "price": lvl, "quantity": quantity, "result": res
        })
    return open_orders

# דוגמה
if __name__ == "__main__":
    open_orders = execute_grid(
        "BTCUSDT", budget=100, grid_count=8, grid_pct=0.5,
        leverage=5, futures=True, direction="BOTH", tp_pct=1, sl_pct=1
    )
    print("Grid orders:", open_orders)



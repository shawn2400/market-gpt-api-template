import logging

def get_binance_client(is_futures):
    from utils.binance_client import client
    return client

def get_symbol_step_size(symbol, is_futures):
    client = get_binance_client(is_futures)
    try:
        info = client.futures_exchange_info() if is_futures else client.get_exchange_info()
        for s in info['symbols']:
            if s['symbol'] == symbol:
                for f in s['filters']:
                    if f['filterType'] == 'LOT_SIZE':
                        return float(f['stepSize'])
    except Exception as e:
        logging.error(f"לא ניתן לאתר stepSize ל־{symbol}: {e}")
    return 0.01

def round_quantity(quantity, step_size):
    from math import floor
    return floor(quantity / step_size) * step_size

def build_grid_levels(entry_price, grid_size, gap_pct, side, two_sided=False):
    """יוצר רמות גריד בכיוון אחד או דו־צדדי"""
    levels = []
    for i in range(grid_size):
        pct_shift = (i + 1) * gap_pct / 100
        # צד אחד
        if not two_sided:
            price = entry_price * (1 - pct_shift) if side == "BUY" else entry_price * (1 + pct_shift)
            levels.append(round(price, 6))
        # דו־צדדי (גם קנייה למטה וגם מכירה למעלה)
        else:
            long_price = entry_price * (1 - pct_shift)
            short_price = entry_price * (1 + pct_shift)
            levels.append({'side': 'BUY', 'price': round(long_price, 6)})
            levels.append({'side': 'SELL', 'price': round(short_price, 6)})
    return levels

def grid_trade(
    symbol: str,
    entry_price: float,
    grid_size: int = 6,
    gap_pct: float = 0.35,
    budget_usd: float = 100,
    is_futures: bool = False,
    leverage: int = 1,
    auto_close: bool = True,
    sl_pct: float = 0.6,
    tp_pct: float = 0.6,
    two_sided: bool = True,
):
    """
    גריד ב־Binance Spot/Futures עם TP/SL
    דו־כיווני (גם BUY גם SELL) – אם two_sided=True, אחרת צד בודד (רק BUY/SELL)
    """
    client = get_binance_client(is_futures)
    step_size = get_symbol_step_size(symbol, is_futures)
    total_orders = grid_size * 2 if two_sided else grid_size
    qty_per_order = budget_usd / total_orders / entry_price * (leverage if is_futures else 1)
    qty_per_order = round_quantity(qty_per_order, step_size)

    results = []
    levels = build_grid_levels(entry_price, grid_size, gap_pct, "BUY", two_sided=two_sided)
    for i, lvl in enumerate(levels):
        if two_sided:
            side = lvl['side']
            price = lvl['price']
        else:
            side = "BUY"
            price = lvl

        try:
            # פקודת גריד (LIMIT)
            order_args = dict(
                symbol=symbol,
                side=side,
                type="LIMIT",
                price=round(price, 4),
                quantity=qty_per_order,
                timeInForce="GTC"
            )
            if is_futures:
                order = client.futures_create_order(**order_args)
            else:
                order = client.create_order(**order_args)
            logging.info(f"✔️ {side} GRID order {symbol} @ {price} qty={qty_per_order} (spot={not is_futures})")
            # פקודות סגירה אוטומטית (TP/SL)
            tp_price = price * (1 + tp_pct/100) if side == "BUY" else price * (1 - tp_pct/100)
            sl_price = price * (1 - sl_pct/100) if side == "BUY" else price * (1 + sl_pct/100)
            if auto_close:
                close_side = "SELL" if side == "BUY" else "BUY"
                if is_futures:
                    # TP (LIMIT) – ב־Futures אפשר גם TAKE_PROFIT_MARKET, לבחירתך
                    client.futures_create_order(
                        symbol=symbol,
                        side=close_side,
                        type="TAKE_PROFIT_MARKET",
                        stopPrice=round(tp_price, 4),
                        closePosition=False,
                        quantity=qty_per_order,
                        timeInForce="GTC"
                    )
                    # SL (STOP_MARKET)
                    client.futures_create_order(
                        symbol=symbol,
                        side=close_side,
                        type="STOP_MARKET",
                        stopPrice=round(sl_price, 4),
                        closePosition=False,
                        quantity=qty_per_order,
                        timeInForce="GTC"
                    )
                else:
                    # ב־Spot אפשר רק Limit/Market – לכן TP/SL בהיגיון פשוט (אפשר גם API אחר)
                    pass
            results.append({
                "order": order,
                "tp": tp_price,
                "sl": sl_price,
                "side": side,
                "price": price
            })
        except Exception as e:
            logging.error(f"❌ שגיאה בפקודת גריד ({symbol}, {side}, {price}): {e}")

    return results

# דוגמה להרצה מהירה – דו־צדדי FUTURES
if __name__ == "__main__":
    grid_trade(
        symbol="BTCUSDT",
        entry_price=68000,
        grid_size=4,
        gap_pct=0.4,
        budget_usd=200,
        is_futures=True,
        leverage=10,
        auto_close=True,
        two_sided=True,  # דו־כיווני
        sl_pct=0.65,
        tp_pct=0.55,
    )

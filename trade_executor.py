# trade_executor.py

from services.executor_core import execute_trade_live

def execute_single_trade(symbol, entry, stop, tp, direction, leverage=20, budget=100, use_grid=False):
    """
    מבצע טרייד אחד בפועל עם הפרמטרים שנשלחו.
    """
    return execute_trade_live(
        symbol=symbol,
        entry=entry,
        stop=stop,
        tp=tp,
        direction=direction,
        leverage=leverage,
        budget_usd=budget,
        use_grid=use_grid
    )

def execute_multiple_trades(trade_list):
    """
    מבצע סדרת טריידים בבת אחת לפי רשימת טריידים.
    כל טרייד הוא dict עם השדות:
    symbol, entry, stop, tp, direction, leverage, budget, use_grid
    """
    results = []
    for trade in trade_list:
        try:
            result = execute_trade_live(
                symbol=trade["symbol"],
                entry=trade["entry"],
                stop=trade["stop"],
                tp=trade["tp"],
                direction=trade["direction"],
                leverage=trade.get("leverage", 20),
                budget_usd=trade.get("budget", 100),
                use_grid=trade.get("use_grid", False)
            )
            results.append({"symbol": trade["symbol"], "status": "success", "result": result})
        except Exception as e:
            results.append({"symbol": trade["symbol"], "status": "error", "error": str(e)})
    return results












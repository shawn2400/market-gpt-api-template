from utils.data_fetcher import fetch_klines
from utils.backtest_utils import run_backtest

@router.get("/", response_model=BacktestResult)
async def backtest(
    symbol: str,
    strategy: str = Query("ema_crossover", description="Strategy name"),
    limit: int = Query(500, ge=50, le=1000, description="מספר נרות היסטוריים לבדיקה"),
    max_trades: int = Query(200, ge=50, le=500, description="מספר מקסימלי של טריידים שיוחזרו ללקוח"),
    interval: str = Query("1h", description="טיים פריים לנרות")
):
    """
    מריץ Backtest (מוגבל ל־1000 candles).
    """
    df = fetch_klines(symbol, interval=interval, limit=limit)
    raw: Dict[str, Any] = run_backtest(df=df, strategy=strategy, initial_balance=1000.0)

    summary = BacktestSummary(
        n_trades_total=raw["n_trades"],
        n_trades_returned=min(len(raw["trades"]), max_trades),
        final_balance=raw["final_balance"],
        profit_pct=raw["profit_pct"],
    )

    trades = [BacktestTrade(**t) for t in raw.get("trades", [])[-max_trades:]]

    return BacktestResult(
        ok=True,
        symbol=symbol,
        strategy=strategy,
        summary=summary,
        trades=trades,
    )
















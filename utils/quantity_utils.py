import math
from typing import Any
from utils.precision_utils import get_precision_info
from utils.binance_client import client


def calculate_quantity_usdt(symbol: str, usdt_amount: float) -> float:
    """
    Compute quantity of a symbol based on a given USDT amount.
    """
    ticker = client.get_symbol_ticker(symbol=symbol)
    price = float(ticker['price'])
    raw_qty = usdt_amount / price

    precision = get_precision_info(symbol)['quantity_precision']
    return round(raw_qty, precision)


def auto_risk_allocation(symbol: str, risk_usd: float) -> float:
    """
    Compute trade quantity so that risk (in USD) does not exceed risk_usd.
    Assumption: risk = position value (quantity * price) without stop-loss.
    """
    ticker = client.get_symbol_ticker(symbol=symbol)
    price = float(ticker['price'])

    raw_qty = risk_usd / price
    precision = get_precision_info(symbol)['quantity_precision']
    return round(raw_qty, precision)


def calculate_quantity(symbol: str, price: float, leverage: float, budget: float) -> float:
    """
    Compute quantity based on budget, price, and leverage.
    Round down to step size according to Binance rules.
    """
    if price <= 0 or leverage <= 0 or budget <= 0:
        return 0.0

    notional = budget * leverage
    raw_qty = notional / price

    precision_info: Any = get_precision_info(symbol)
    # expecting 'stepSize' in precision_info, else default to smallest increment
    step_size = float(precision_info.get('stepSize', 1 / (10 ** precision_info['quantity_precision'])))

    # determine decimal precision from step size
    precision = int(round(-math.log10(step_size))) if step_size < 1 else 0
    quantity = math.floor(raw_qty / step_size) * step_size

    return round(quantity, precision)






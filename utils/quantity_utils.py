# utils/quantity_utils.py

def calculate_quantity(budget_usd, entry_price, leverage):
    try:
        qty = (budget_usd * leverage) / entry_price
        return round(qty, 3)
    except Exception as e:
        print(f"[!] שגיאה בחישוב כמות: {e}")
        return 0

def auto_risk_allocation(entry_price, stop_price, total_budget, risk_percent=2):
    try:
        risk_per_trade = total_budget * (risk_percent / 100)
        risk_per_unit = abs(entry_price - stop_price)
        if risk_per_unit == 0:
            raise ValueError("Stop price and entry price זהים — אי אפשר לחשב סיכון")
        qty = risk_per_trade / risk_per_unit
        capital_required = (qty * entry_price)
        return min(capital_required, total_budget)
    except Exception as e:
        print(f"[!] שגיאה בחישוב סיכון: {e}")
        return total_budget

def generate_grid_levels(entry_price, tp_price, levels=3):
    grid = []
    diff = tp_price - entry_price
    for i in range(1, levels + 1):
        grid_price = entry_price + (diff * i / levels)
        grid.append(round(grid_price, 2))
    return grid



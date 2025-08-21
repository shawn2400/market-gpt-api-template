# utils/trade_manager.py
import time
import json
from typing import List, Dict
from utils.redis_client import redis_client

TRADES_KEY = "trades:all"

def _load_trades() -> List[Dict]:
    if not redis_client:
        return []
    try:
        raw = redis_client.get(TRADES_KEY)
        return json.loads(raw) if raw else []
    except Exception:
        return []

def _save_trades(trades: List[Dict]) -> None:
    if not redis_client:
        return
    try:
        redis_client.set(TRADES_KEY, json.dumps(trades), ex=86400)
    except Exception:
        pass

def get_open_trades() -> List[Dict]:
    trades = _load_trades()
    return [t for t in trades if t.get("status") == "OPEN"]

def get_trade_history(limit: int = 50) -> List[Dict]:
    trades = _load_trades()
    return list(reversed([t for t in trades if t.get("status") != "OPEN"]))[:limit]

def add_trade(symbol: str, side: str, entry_price: float, qty: float) -> Dict:
    trade = {
        "id": str(int(time.time() * 1000)),
        "symbol": symbol.upper(),
        "side": side.upper(),
        "entry_price": entry_price,
        "qty": qty,
        "pnl": 0.0,
        "status": "OPEN",
        "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    trades = _load_trades()
    trades.append(trade)
    _save_trades(trades)
    return trade

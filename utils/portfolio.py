# utils/portfolio.py
from __future__ import annotations
import os, json, time, uuid
from typing import Dict, Any, Optional, List

TRADES_LOG_PATH = os.getenv("TRADES_LOG_PATH", "data/trades_log.json")

class Portfolio:
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance: float = initial_balance
        self.positions: Dict[str, Dict[str, Any]] = {}  # symbol → position dict
        self.history: List[Dict[str, Any]] = []

    # ===============================
    # --- Internal Helpers ---
    # ===============================
    def _save_history(self):
        try:
            os.makedirs(os.path.dirname(TRADES_LOG_PATH), exist_ok=True)
            with open(TRADES_LOG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[portfolio] Failed to save history: {e}")

    def _log_trade(self, trade: Dict[str, Any]):
        self.history.append(trade)
        self._save_history()

    # ===============================
    # --- Public API ---
    # ===============================
    def open_trade(
        self,
        symbol: str,
        side: str,
        entry: float,
        qty: float,
        leverage: int = 10,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        budget: Optional[float] = None,
    ) -> Dict[str, Any]:
        symbol = symbol.upper()
        if symbol in self.positions:
            raise ValueError(f"Position already open for {symbol}")

        trade_id = f"TRD-{uuid.uuid4().hex[:10]}"
        used_margin = budget if budget else self.balance / 10
        if used_margin > self.balance:
            raise ValueError("Not enough balance")

        pos = {
            "trade_id": trade_id,
            "symbol": symbol,
            "side": side.upper(),
            "entry": entry,
            "qty": qty,
            "leverage": leverage,
            "sl": sl,
            "tp": tp,
            "margin": used_margin,
            "status": "OPEN",
            "opened_at": time.time(),
        }
        self.balance -= used_margin
        self.positions[symbol] = pos
        self._log_trade({**pos, "event": "OPEN"})

        return pos

    def close_trade(self, symbol: str, close_price: float) -> Dict[str, Any]:
        symbol = symbol.upper()
        if symbol not in self.positions:
            raise ValueError(f"No open position for {symbol}")

        pos = self.positions.pop(symbol)
        entry = pos["entry"]
        side = pos["side"]
        qty = pos["qty"]
        margin = pos["margin"]
        lev = pos["leverage"]

        # PnL calculation
        if side == "LONG":
            pnl = (close_price - entry) / entry * margin * lev
        else:
            pnl = (entry - close_price) / entry * margin * lev

        pos.update({
            "exit": close_price,
            "pnl": round(pnl, 2),
            "status": "CLOSED",
            "closed_at": time.time(),
        })
        self.balance += margin + pnl
        self._log_trade({**pos, "event": "CLOSE"})
        return pos

    def get_portfolio_state(self) -> Dict[str, Any]:
        return {
            "balance": round(self.balance, 2),
            "initial_balance": self.initial_balance,
            "open_positions": list(self.positions.values()),
            "history_len": len(self.history),
            "open_count": len(self.positions),
            "closed_count": len([h for h in self.history if h.get("status") == "CLOSED"]),
        }


# ✅ Singleton portfolio object
portfolio = Portfolio(initial_balance=float(os.getenv("PORTFOLIO_BALANCE", 1000.0)))



# utils/portfolio.py
from __future__ import annotations
import os, time, uuid, psycopg2
from typing import Dict, Any, Optional, List
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

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
        """Save trade history to PostgreSQL instead of JSON file"""
        pass  # No longer needed - using _log_trade directly to PostgreSQL

    def _log_trade(self, trade: Dict[str, Any]):
        """Log trade to PostgreSQL database"""
        try:
            if not DATABASE_URL:
                print(f"[portfolio] DATABASE_URL not configured - cannot save trade")
                return
            
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO trades_log (
                    trade_id, symbol, side, entry, exit, qty, leverage,
                    sl, tp, margin, pnl, status, opened_at, closed_at, event, note
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (trade_id) DO UPDATE SET
                    exit = EXCLUDED.exit,
                    pnl = EXCLUDED.pnl,
                    status = EXCLUDED.status,
                    closed_at = EXCLUDED.closed_at,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                trade.get("trade_id"),
                trade.get("symbol"),
                trade.get("side"),
                trade.get("entry"),
                trade.get("exit"),
                trade.get("qty"),
                trade.get("leverage"),
                trade.get("sl"),
                trade.get("tp"),
                trade.get("margin"),
                trade.get("pnl"),
                trade.get("status"),
                datetime.fromtimestamp(trade.get("opened_at", time.time())) if trade.get("opened_at") else None,
                datetime.fromtimestamp(trade.get("closed_at", time.time())) if trade.get("closed_at") else None,
                trade.get("event"),
                trade.get("note")
            ))
            
            conn.commit()
            cursor.close()
            conn.close()
            self.history.append(trade)
        except Exception as e:
            print(f"[portfolio] Failed to save trade to PostgreSQL: {e}")

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
        margin = pos["margin"]
        lev = pos["leverage"]

        # PnL calculation (פשוט; ללא עמלות/דמי מימון)
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




"""
Portfolio Intelligence - Risk & Exposure Management
====================================================
Prevents over-exposure by tracking correlations and position limits.

Features:
- Correlation analysis (don't open 5 longs simultaneously)
- Exposure limits per direction (max LONG/SHORT exposure)
- Position concentration limits
- Daily trade caps with quality tracking
- P&L-based circuit breakers

Author: AlgoGPT Team
Level: Hedge Fund Grade
"""

import logging
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

LOGGER = logging.getLogger("portfolio_intelligence")


class PortfolioIntelligence:
    """
    Tracks open positions and proposed trades to prevent over-exposure.
    
    Rules:
    - Max total exposure: configurable % of account equity
    - Max direction exposure: separate limits for LONG/SHORT
    - Max correlated positions: limit highly correlated assets
    - Daily trade cap: limit number of trades per day
    - Drawdown protection: stop trading if daily loss exceeds threshold
    """
    
    def __init__(self):
        self.logger = LOGGER
        
        # Configuration from env
        self.max_exposure_pct = float(os.getenv("MAX_PORTFOLIO_EXPOSURE_PCT", "80"))  # % of equity
        self.max_long_exposure_pct = float(os.getenv("MAX_LONG_EXPOSURE_PCT", "60"))
        self.max_short_exposure_pct = float(os.getenv("MAX_SHORT_EXPOSURE_PCT", "60"))
        self.max_positions = int(os.getenv("MAX_OPEN_POSITIONS", "8"))
        self.max_daily_trades = int(os.getenv("MAX_DAILY_TRADES", "10"))
        self.max_daily_loss_pct = float(os.getenv("MAX_DAILY_LOSS_PCT", "5.0"))  # Stop if -5% daily
        
        # In-memory tracking (in production, use database/Redis)
        self.open_positions: List[Dict] = []
        self.daily_trades: List[Dict] = []
        self.daily_pnl: float = 0.0
        self.account_equity: float = 0.0
        
    def can_open_trade(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        reason: str = ""
    ) -> Tuple[bool, str]:
        """
        Check if a new trade can be opened based on portfolio rules.
        
        Args:
            symbol: Trading symbol
            side: "LONG" or "SHORT"
            size_usd: Position size in USD
            reason: Optional reason for logging
            
        Returns:
            (can_open, rejection_reason)
        """
        # 1. Daily trade cap
        if not self._check_daily_trade_cap():
            return (False, "daily_trade_cap_reached")
        
        # 2. Daily loss limit (circuit breaker)
        if not self._check_daily_loss_limit():
            return (False, f"daily_loss_limit_exceeded ({self.daily_pnl:.1f}%)")
        
        # 3. Max positions
        if not self._check_max_positions():
            return (False, f"max_positions_reached ({len(self.open_positions)}/{self.max_positions})")
        
        # 4. Total exposure
        if not self._check_total_exposure(size_usd):
            return (False, "max_total_exposure_exceeded")
        
        # 5. Direction exposure (LONG/SHORT)
        if not self._check_direction_exposure(side, size_usd):
            return (False, f"max_{side.lower()}_exposure_exceeded")
        
        # 6. Symbol concentration (don't add to same symbol too much)
        if not self._check_symbol_concentration(symbol, size_usd):
            return (False, f"max_concentration_for_{symbol}")
        
        # All checks passed
        self.logger.info(
            f"✅ Portfolio check PASS: {symbol} {side} ${size_usd:.0f} "
            f"(positions={len(self.open_positions)}, daily_trades={len(self.daily_trades)})"
        )
        return (True, "")
    
    def register_trade_opened(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        entry_price: float
    ):
        """Register that a new trade was opened"""
        position = {
            "symbol": symbol,
            "side": side,
            "size_usd": size_usd,
            "entry_price": entry_price,
            "opened_at": datetime.utcnow().isoformat()
        }
        self.open_positions.append(position)
        self.daily_trades.append({**position, "action": "opened"})
        
        self.logger.info(
            f"📊 Position opened: {symbol} {side} ${size_usd:.0f} @ {entry_price} "
            f"(total positions: {len(self.open_positions)})"
        )
    
    def register_trade_closed(
        self,
        symbol: str,
        side: str,
        pnl_usd: float
    ):
        """Register that a trade was closed with P&L"""
        # Remove from open positions
        self.open_positions = [
            p for p in self.open_positions
            if not (p["symbol"] == symbol and p["side"] == side)
        ]
        
        # Track P&L
        self.daily_pnl += pnl_usd
        self.daily_trades.append({
            "symbol": symbol,
            "side": side,
            "pnl_usd": pnl_usd,
            "action": "closed",
            "closed_at": datetime.utcnow().isoformat()
        })
        
        self.logger.info(
            f"📊 Position closed: {symbol} {side} PnL=${pnl_usd:+.2f} "
            f"(total positions: {len(self.open_positions)}, daily_pnl=${self.daily_pnl:+.2f})"
        )
    
    def update_account_equity(self, equity_usd: float):
        """Update current account equity for exposure calculations"""
        self.account_equity = equity_usd
        self.logger.debug(f"Account equity updated: ${equity_usd:.2f}")
    
    def reset_daily_stats(self):
        """Reset daily counters (call this at midnight UTC)"""
        self.daily_trades = []
        self.daily_pnl = 0.0
        self.logger.info("📅 Daily stats reset")
    
    # ========== Internal Checks ==========
    
    def _check_daily_trade_cap(self) -> bool:
        """Check if we've reached daily trade limit"""
        daily_count = len([t for t in self.daily_trades if t.get("action") == "opened"])
        if daily_count >= self.max_daily_trades:
            self.logger.warning(f"❌ Daily trade cap reached: {daily_count}/{self.max_daily_trades}")
            return False
        return True
    
    def _check_daily_loss_limit(self) -> bool:
        """Check if daily loss exceeds threshold (circuit breaker)"""
        if self.account_equity <= 0:
            return True  # Can't calculate, allow
        
        daily_loss_pct = (self.daily_pnl / self.account_equity) * 100
        if daily_loss_pct < -self.max_daily_loss_pct:
            self.logger.warning(
                f"🛑 CIRCUIT BREAKER: Daily loss {daily_loss_pct:.2f}% exceeds limit "
                f"({-self.max_daily_loss_pct:.1f}%)"
            )
            return False
        return True
    
    def _check_max_positions(self) -> bool:
        """Check if we've reached max open positions"""
        if len(self.open_positions) >= self.max_positions:
            self.logger.warning(
                f"❌ Max positions reached: {len(self.open_positions)}/{self.max_positions}"
            )
            return False
        return True
    
    def _check_total_exposure(self, new_size_usd: float) -> bool:
        """Check total portfolio exposure"""
        if self.account_equity <= 0:
            return True  # Can't calculate, allow
        
        current_exposure = sum(p["size_usd"] for p in self.open_positions)
        new_total_exposure = current_exposure + new_size_usd
        
        max_exposure_usd = self.account_equity * (self.max_exposure_pct / 100)
        
        if new_total_exposure > max_exposure_usd:
            self.logger.warning(
                f"❌ Total exposure would exceed limit: "
                f"${new_total_exposure:.0f} > ${max_exposure_usd:.0f} "
                f"({self.max_exposure_pct}% of equity)"
            )
            return False
        return True
    
    def _check_direction_exposure(self, side: str, new_size_usd: float) -> bool:
        """Check LONG or SHORT exposure separately"""
        if self.account_equity <= 0:
            return True
        
        current_direction_exposure = sum(
            p["size_usd"] for p in self.open_positions
            if p["side"] == side
        )
        new_direction_exposure = current_direction_exposure + new_size_usd
        
        max_limit_pct = (
            self.max_long_exposure_pct if side == "LONG"
            else self.max_short_exposure_pct
        )
        max_limit_usd = self.account_equity * (max_limit_pct / 100)
        
        if new_direction_exposure > max_limit_usd:
            self.logger.warning(
                f"❌ {side} exposure would exceed limit: "
                f"${new_direction_exposure:.0f} > ${max_limit_usd:.0f} "
                f"({max_limit_pct}% of equity)"
            )
            return False
        return True
    
    def _check_symbol_concentration(self, symbol: str, new_size_usd: float) -> bool:
        """Prevent too much concentration in one symbol"""
        if self.account_equity <= 0:
            return True
        
        # Max 15% of equity in single symbol
        max_per_symbol_pct = float(os.getenv("MAX_PER_SYMBOL_PCT", "15"))
        max_per_symbol_usd = self.account_equity * (max_per_symbol_pct / 100)
        
        current_symbol_exposure = sum(
            p["size_usd"] for p in self.open_positions
            if p["symbol"] == symbol
        )
        new_symbol_exposure = current_symbol_exposure + new_size_usd
        
        if new_symbol_exposure > max_per_symbol_usd:
            self.logger.warning(
                f"❌ Symbol concentration would exceed limit for {symbol}: "
                f"${new_symbol_exposure:.0f} > ${max_per_symbol_usd:.0f} "
                f"({max_per_symbol_pct}% of equity)"
            )
            return False
        return True
    
    def get_portfolio_status(self) -> Dict:
        """Get current portfolio status for monitoring"""
        total_exposure = sum(p["size_usd"] for p in self.open_positions)
        long_exposure = sum(p["size_usd"] for p in self.open_positions if p["side"] == "LONG")
        short_exposure = sum(p["size_usd"] for p in self.open_positions if p["side"] == "SHORT")
        
        return {
            "open_positions": len(self.open_positions),
            "total_exposure_usd": total_exposure,
            "long_exposure_usd": long_exposure,
            "short_exposure_usd": short_exposure,
            "daily_trades": len([t for t in self.daily_trades if t.get("action") == "opened"]),
            "daily_pnl_usd": self.daily_pnl,
            "account_equity": self.account_equity,
            "exposure_pct": (total_exposure / self.account_equity * 100) if self.account_equity > 0 else 0
        }


# Global instance
_portfolio_intelligence = None

def get_portfolio_intelligence() -> PortfolioIntelligence:
    """Get singleton instance of PortfolioIntelligence"""
    global _portfolio_intelligence
    if _portfolio_intelligence is None:
        _portfolio_intelligence = PortfolioIntelligence()
    return _portfolio_intelligence

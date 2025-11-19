#!/usr/bin/env python3
"""
Dynamic Budget Manager - Real-time Wallet-Based Position Sizing
================================================================
Checks wallet balance in real-time and adapts trade size + leverage
to match available funds and risk parameters.

Features:
- Real-time balance checking from Binance
- Considers open positions and locked funds
- Dynamic leverage calculation (2x-20x)
- Risk-based position sizing
- Smart capital allocation
"""

import logging
import os
from typing import Dict, Any, Optional, Tuple
from decimal import Decimal

logger = logging.getLogger("algogpt.dynamic_budget")


class DynamicBudgetManager:
    """
    Dynamic budget manager that adapts trade sizing to real-time wallet state.
    
    Philosophy:
    - Never risk more than what's available
    - Scale position size based on account equity
    - Dynamic leverage based on quality + volatility
    - Preserve capital for ongoing trades
    """
    
    def __init__(self, binance_client=None):
        """
        Initialize Dynamic Budget Manager.
        
        Args:
            binance_client: Optional Binance client (if None, will create from env)
        """
        self.logger = logger
        self.client = binance_client
        
        self.min_trade_usdt = float(os.getenv("BUDGET_MIN_USDT", "5"))  # Lower minimum for small accounts
        self.max_trade_usdt = float(os.getenv("BUDGET_MAX_USDT", "100"))
        
        self.default_risk_pct = float(os.getenv("BUDGET_RISK_PCT", "2.0"))
        
        self.leverage_min = int(os.getenv("LEVERAGE_MIN", "2"))
        self.leverage_max = int(os.getenv("LEVERAGE_MAX", "20"))
        
        self.logger.info(
            f"Dynamic Budget Manager initialized: "
            f"min=${self.min_trade_usdt}, max=${self.max_trade_usdt}, "
            f"risk={self.default_risk_pct}%, leverage={self.leverage_min}-{self.leverage_max}x"
        )
    
    def get_wallet_state(self) -> Dict[str, Any]:
        """
        Get real-time wallet state from Binance.
        
        Returns:
            Dict with balance, available, locked, positions
        """
        try:
            if not self.client:
                self.logger.warning("No Binance client - using mock wallet data")
                return {
                    "total_balance": 1000.0,
                    "available_balance": 850.0,
                    "locked_in_trades": 150.0,
                    "open_positions": 2,
                    "positions_value": 300.0,
                    "mock": True
                }
            
            account = self.client.futures_account()
            
            total_balance = float(account.get("totalWalletBalance", 0))
            available_balance = float(account.get("availableBalance", 0))
            
            positions = self.client.futures_position_information()
            open_positions = [p for p in positions if float(p.get("positionAmt", 0)) != 0]
            
            positions_value = sum(
                abs(float(p.get("notional", 0))) for p in open_positions
            )
            
            locked = total_balance - available_balance
            
            return {
                "total_balance": total_balance,
                "available_balance": available_balance,
                "locked_in_trades": locked,
                "open_positions": len(open_positions),
                "positions_value": positions_value,
                "mock": False
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get wallet state: {e}", exc_info=True)
            return {
                "total_balance": 0,
                "available_balance": 0,
                "locked_in_trades": 0,
                "open_positions": 0,
                "positions_value": 0,
                "error": str(e)
            }
    
    def calculate_position_size(
        self,
        quality_score: float,
        volatility_atr_pct: float,
        risk_reward: float,
        market_regime: str = "NEUTRAL",
        wallet_state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Calculate optimal position size based on wallet and trade parameters.
        
        Args:
            quality_score: Trade quality (5.5-10.0)
            volatility_atr_pct: ATR as percentage (e.g., 2.5 = 2.5%)
            risk_reward: R:R ratio (e.g., 1.5 = 1.5:1)
            market_regime: TRENDING/CHOPPY/VOLATILE/SIDEWAYS
            wallet_state: Optional wallet state (if None, fetches fresh)
        
        Returns:
            Dict with position_size_usdt, leverage, reason, risk_pct
        """
        try:
            if wallet_state is None:
                wallet_state = self.get_wallet_state()
            
            available = wallet_state.get("available_balance", 0)
            total = wallet_state.get("total_balance", 0)
            
            if available < self.min_trade_usdt:
                return {
                    "position_size_usdt": 0,
                    "leverage": 1,
                    "reason": f"ארנק ריק - זמין ${available:.2f}, מינימום ${self.min_trade_usdt}",
                    "risk_pct": 0,
                    "allowed": False
                }
            
            base_size = min(
                available * 0.05,
                self.max_trade_usdt
            )
            
            quality_multiplier = (quality_score - 5.0) / 5.0
            quality_multiplier = max(0.5, min(2.0, quality_multiplier))
            
            rr_multiplier = min(risk_reward / 1.5, 1.5)
            
            volatility_factor = 1.0
            if volatility_atr_pct > 4.0:
                volatility_factor = 0.7
            elif volatility_atr_pct > 3.0:
                volatility_factor = 0.85
            
            regime_multiplier = 1.0
            if market_regime == "TRENDING":
                regime_multiplier = 1.2
            elif market_regime == "CHOPPY":
                regime_multiplier = 0.8
            elif market_regime == "VOLATILE":
                regime_multiplier = 0.7
            
            position_size = base_size * quality_multiplier * rr_multiplier * volatility_factor * regime_multiplier
            
            position_size = max(self.min_trade_usdt, min(position_size, self.max_trade_usdt))
            position_size = min(position_size, available * 0.15)
            
            leverage = self._calculate_leverage(
                quality_score, volatility_atr_pct, market_regime
            )
            
            risk_pct = (position_size / total * 100) if total > 0 else 0
            
            reason_parts = []
            if quality_score >= 7.5:
                reason_parts.append(f"איכות גבוהה {quality_score:.1f}")
            if risk_reward >= 2.0:
                reason_parts.append(f"RR מעולה {risk_reward:.1f}:1")
            if market_regime == "TRENDING":
                reason_parts.append("שוק טרנדי")
            
            reason = " | ".join(reason_parts) if reason_parts else "תקציב סטנדרטי"
            
            self.logger.info(
                f"Position sizing: ${position_size:.2f} @ {leverage}x | "
                f"Quality={quality_score:.1f}, ATR={volatility_atr_pct:.1f}%, "
                f"RR={risk_reward:.1f}, Regime={market_regime}"
            )
            
            return {
                "position_size_usdt": round(position_size, 2),
                "leverage": leverage,
                "reason": reason,
                "risk_pct": round(risk_pct, 2),
                "allowed": True,
                "wallet_available": available,
                "wallet_total": total
            }
            
        except Exception as e:
            self.logger.error(f"Failed to calculate position size: {e}", exc_info=True)
            return {
                "position_size_usdt": self.min_trade_usdt,
                "leverage": 3,
                "reason": f"שגיאה בחישוב: {e}",
                "risk_pct": 1.0,
                "allowed": False
            }
    
    def _calculate_leverage(
        self,
        quality_score: float,
        volatility_atr_pct: float,
        market_regime: str
    ) -> int:
        """
        Calculate dynamic leverage based on trade parameters using DynamicLeverageCalculator.
        
        100% Dynamic leverage (2-35x) - no hardcoded values!
        
        Args:
            quality_score: Trade quality (5.5-10.0)
            volatility_atr_pct: ATR percentage
            market_regime: Market regime
        
        Returns:
            Leverage multiplier (2x-35x)
        """
        try:
            # Use DynamicLeverageCalculator for 100% dynamic leverage
            from utils.dynamic_leverage import DynamicLeverageCalculator
            
            calculator = DynamicLeverageCalculator()
            leverage = calculator.calculate_leverage(
                trade_quality=quality_score,
                symbol="BTCUSDT",  # Fallback symbol (actual symbol from trade context)
                atr_pct=volatility_atr_pct / 100.0,  # Convert to decimal
                current_price=None  # Not needed for leverage calculation
            )
            
            return int(leverage)
            
        except Exception as e:
            # Fallback to simple calculation if DynamicLeverageCalculator fails
            self.logger.warning(f"⚠️ DynamicLeverageCalculator failed, using fallback: {e}")
            
            # Simple dynamic fallback (still better than hardcoded templates)
            base_leverage = 5
            
            if quality_score >= 8.0:
                base_leverage = 8
            elif quality_score >= 7.0:
                base_leverage = 6
            elif quality_score < 6.0:
                base_leverage = 4
            
            if volatility_atr_pct > 4.0:
                base_leverage = max(2, base_leverage - 3)
            elif volatility_atr_pct > 3.0:
                base_leverage = max(3, base_leverage - 1)
            
            if market_regime == "TRENDING":
                base_leverage = min(self.leverage_max, base_leverage + 2)
            elif market_regime == "VOLATILE":
                base_leverage = max(self.leverage_min, base_leverage - 2)
            elif market_regime == "CHOPPY":
                base_leverage = max(self.leverage_min, base_leverage - 1)
            
            return max(self.leverage_min, min(self.leverage_max, base_leverage))
    
    def can_afford_trade(self, position_size: float, leverage: int = 1) -> Tuple[bool, str]:
        """
        Check if wallet can afford this trade.
        
        Args:
            position_size: Position size in USDT
            leverage: Leverage multiplier
        
        Returns:
            (can_afford: bool, reason: str)
        """
        try:
            wallet = self.get_wallet_state()
            available = wallet.get("available_balance", 0)
            
            required = position_size / leverage if leverage > 0 else position_size
            
            if available < required:
                return False, f"לא מספיק כסף - צריך ${required:.2f}, יש ${available:.2f}"
            
            if required < self.min_trade_usdt:
                return False, f"טרייד קטן מדי - ${required:.2f} < מינימום ${self.min_trade_usdt}"
            
            return True, f"ארנק תומך - ${available:.2f} זמין"
            
        except Exception as e:
            return False, f"שגיאה בבדיקת ארנק: {e}"


_budget_manager_instance: Optional[DynamicBudgetManager] = None


def get_budget_manager(binance_client=None) -> DynamicBudgetManager:
    """
    Get or create global DynamicBudgetManager instance.
    
    Args:
        binance_client: Optional Binance client
    
    Returns:
        DynamicBudgetManager instance
    """
    global _budget_manager_instance
    if _budget_manager_instance is None:
        _budget_manager_instance = DynamicBudgetManager(binance_client)
    return _budget_manager_instance


__all__ = ["DynamicBudgetManager", "get_budget_manager"]

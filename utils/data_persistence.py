#!/usr/bin/env python3
# utils/data_persistence.py
"""
Data Persistence Module - Full Implementation
==============================================
This module provides database persistence for market analysis data.

Features:
- Save/Load market state analysis
- Save/Load trade analysis data
- Full PostgreSQL and SQLite support
"""

import logging
import json
import time
from typing import Dict, Any, Optional

logger = logging.getLogger("algogpt.data_persistence")


class DataPersistence:
    """
    Data persistence interface for market intelligence and analysis data.
    
    Provides database persistence for market states and trade analysis.
    Supports both PostgreSQL and SQLite through utils.db infrastructure.
    """
    
    def __init__(self):
        self.logger = logger
        self.logger.info("DataPersistence initialized with database backend")
    
    def save_market_state(
        self,
        symbol: str,
        regime: str,
        mood: str,
        volatility: str,
        trend_strength: float,
        strategy: str,
        min_rr: float,
        min_quality: float,
        indicators: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Save market state analysis to database.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            regime: Market regime (trending/sideways/choppy/volatile)
            mood: Market mood (bullish/bearish/neutral)
            volatility: Volatility level (high/medium/low)
            trend_strength: Trend strength score (0-100)
            strategy: Recommended strategy
            min_rr: Minimum risk/reward threshold
            min_quality: Minimum quality threshold
            indicators: Optional dict of indicator values
            
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            from utils.db import _conn, _is_postgres, DB_URL, USE_DB
            
            if not USE_DB:
                self.logger.debug("Database disabled (USE_DB=0), skipping market state save")
                return True
            
            is_pg = _is_postgres(DB_URL)
            
            with _conn() as con:
                if con is None:
                    self.logger.error("Database connection failed")
                    return False
                
                cur = con.cursor()
                
                # Prepare indicators JSON
                indicators_json = json.dumps(indicators) if indicators else None
                
                if is_pg:
                    # PostgreSQL - INSERT with timestamp for backward compatibility
                    cur.execute("""
                        INSERT INTO market_states 
                        (timestamp, symbol, regime, mood, volatility, trend_strength, strategy, 
                         min_rr, min_quality, indicators, created_at, updated_at)
                        VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """, (
                        symbol, regime, mood, volatility, trend_strength, 
                        strategy, min_rr, min_quality, indicators_json
                    ))
                else:
                    # SQLite - INSERT with timestamp for backward compatibility
                    cur.execute("""
                        INSERT INTO market_states 
                        (timestamp, symbol, regime, mood, volatility, trend_strength, strategy, 
                         min_rr, min_quality, indicators, created_at, updated_at)
                        VALUES (strftime('%s', 'now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'), strftime('%s', 'now'))
                    """, (
                        symbol, regime, mood, volatility, trend_strength, 
                        strategy, min_rr, min_quality, indicators_json
                    ))
                    con.commit()
                
                self.logger.debug(
                    f"Market state saved for {symbol}: regime={regime}, mood={mood}, "
                    f"volatility={volatility}, trend_strength={trend_strength:.1f}, "
                    f"strategy={strategy}, min_rr={min_rr:.2f}"
                )
                
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to save market state for {symbol}: {e}", exc_info=True)
            return False
    
    def get_market_state(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve latest market state for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dict with market state data or None if not found
        """
        try:
            from utils.db import _conn, _is_postgres, DB_URL, USE_DB
            
            if not USE_DB:
                self.logger.debug("Database disabled (USE_DB=0), skipping market state load")
                return None
            
            is_pg = _is_postgres(DB_URL)
            
            with _conn() as con:
                if con is None:
                    self.logger.error("Database connection failed")
                    return None
                
                cur = con.cursor()
                
                if is_pg:
                    cur.execute("""
                        SELECT regime, mood, volatility, trend_strength, strategy, 
                               min_rr, min_quality, indicators, created_at, updated_at
                        FROM market_states
                        WHERE symbol = %s
                        ORDER BY updated_at DESC
                        LIMIT 1
                    """, (symbol,))
                else:
                    cur.execute("""
                        SELECT regime, mood, volatility, trend_strength, strategy, 
                               min_rr, min_quality, indicators, created_at, updated_at
                        FROM market_states
                        WHERE symbol = ?
                        ORDER BY updated_at DESC
                        LIMIT 1
                    """, (symbol,))
                
                row = cur.fetchone()
                
                if row:
                    indicators_data = None
                    if row[7]:  # indicators column
                        try:
                            indicators_data = json.loads(row[7])
                        except:
                            pass
                    
                    return {
                        "symbol": symbol,
                        "regime": row[0],
                        "mood": row[1],
                        "volatility": row[2],
                        "trend_strength": row[3],
                        "strategy": row[4],
                        "min_rr": row[5],
                        "min_quality": row[6],
                        "indicators": indicators_data,
                        "created_at": row[8],
                        "updated_at": row[9]
                    }
                
                return None
                
        except Exception as e:
            self.logger.error(f"Failed to load market state for {symbol}: {e}", exc_info=True)
            return None
    
    def save_trade_analysis(
        self,
        symbol: str,
        analysis_type: str,
        data: Dict[str, Any]
    ) -> bool:
        """
        Save trade analysis data.
        
        Args:
            symbol: Trading symbol
            analysis_type: Type of analysis (e.g., "multi_tf", "sentiment")
            data: Analysis data
            
        Returns:
            True if saved successfully
        """
        try:
            from utils.db import _conn, _is_postgres, DB_URL, USE_DB
            
            if not USE_DB:
                self.logger.debug("Database disabled (USE_DB=0), skipping trade analysis save")
                return True
            
            is_pg = _is_postgres(DB_URL)
            
            with _conn() as con:
                if con is None:
                    self.logger.error("Database connection failed")
                    return False
                
                cur = con.cursor()
                
                # Convert data to JSON
                data_json = json.dumps(data)
                timestamp = int(time.time())
                
                if is_pg:
                    cur.execute("""
                        INSERT INTO trade_analysis 
                        (symbol, analysis_type, data, created_at, updated_at)
                        VALUES (%s, %s, %s, NOW(), NOW())
                        ON CONFLICT (symbol, analysis_type) 
                        DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
                    """, (symbol, analysis_type, data_json))
                else:
                    cur.execute("""
                        INSERT OR REPLACE INTO trade_analysis 
                        (symbol, analysis_type, data, created_at, updated_at)
                        VALUES (?, ?, ?, strftime('%s', 'now'), strftime('%s', 'now'))
                    """, (symbol, analysis_type, data_json))
                    con.commit()
                
                self.logger.debug(
                    f"Trade analysis saved for {symbol}: type={analysis_type}, "
                    f"data_keys={list(data.keys())}"
                )
                
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to save trade analysis for {symbol}: {e}", exc_info=True)
            return False


# Global instance
_persistence_instance: Optional[DataPersistence] = None


def get_persistence() -> DataPersistence:
    """
    Get or create global DataPersistence instance.
    
    Returns:
        DataPersistence instance
    """
    global _persistence_instance
    if _persistence_instance is None:
        _persistence_instance = DataPersistence()
    return _persistence_instance


__all__ = ["DataPersistence", "get_persistence"]

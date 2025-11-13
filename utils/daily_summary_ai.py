#!/usr/bin/env python3
# utils/daily_summary_ai.py
"""
Daily Summary with AI-Powered Recommendations
Generate comprehensive daily reports with AI insights
"""
import os
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger("daily_summary_ai")


async def get_daily_kpis() -> Dict[str, Any]:
    """
    Calculate daily KPIs from database
    
    Returns:
        Dict with:
        - total_pnl: Total PnL for today
        - win_rate: Percentage of winning trades
        - best_symbols: Top 3 performing symbols
        - worst_symbols: Top 3 worst performing symbols
        - strategy_stats: Win rates by strategy (GRID, Mean-Reversion, Futures)
        - exit_reasons: Distribution of exit reasons
    """
    try:
        from utils.db import _conn, _is_postgres, DB_URL
        
        if not DB_URL:
            return {"error": "Database not configured"}
        
        is_pg = _is_postgres(DB_URL)
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_ts = today.timestamp()
        
        kpis = {
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "best_symbols": [],
            "worst_symbols": [],
            "strategy_stats": {
                "GRID": {"count": 0, "wins": 0, "pnl": 0.0},
                "MEAN_REVERSION": {"count": 0, "wins": 0, "pnl": 0.0},
                "FUTURES": {"count": 0, "wins": 0, "pnl": 0.0},
            },
            "exit_reasons": {}
        }
        
        with _conn() as con:
            cursor = con.cursor()
            
            # Get all closed positions from today with trade_type
            if is_pg:
                cursor.execute("""
                    SELECT symbol, pnl, status, side, trade_type
                    FROM positions
                    WHERE ts_close >= to_timestamp(%s) AND status = 'CLOSED'
                    ORDER BY ts_close DESC
                """, (today_ts,))
            else:
                cursor.execute("""
                    SELECT symbol, pnl, status, side, trade_type
                    FROM positions
                    WHERE ts_close >= ? AND status = 'CLOSED'
                    ORDER BY ts_close DESC
                """, (today_ts,))
            
            rows = cursor.fetchall()
            
            if not rows:
                logger.info("No closed trades today")
                return kpis
            
            # Calculate KPIs
            symbol_pnl = {}
            for row in rows:
                symbol, pnl, status, side, trade_type = row
                pnl_val = float(pnl) if pnl else 0.0
                
                kpis["total_pnl"] += pnl_val
                kpis["total_trades"] += 1
                if pnl_val > 0:
                    kpis["winning_trades"] += 1
                
                # Track by symbol
                if symbol not in symbol_pnl:
                    symbol_pnl[symbol] = []
                symbol_pnl[symbol].append(pnl_val)
                
                # Track by strategy
                if trade_type and trade_type in kpis["strategy_stats"]:
                    kpis["strategy_stats"][trade_type]["count"] += 1
                    kpis["strategy_stats"][trade_type]["pnl"] += pnl_val
                    if pnl_val > 0:
                        kpis["strategy_stats"][trade_type]["wins"] += 1
            
            # Win rate
            if kpis["total_trades"] > 0:
                kpis["win_rate"] = (kpis["winning_trades"] / kpis["total_trades"]) * 100
            
            # Best/worst symbols
            symbol_summary = {sym: sum(pnls) for sym, pnls in symbol_pnl.items()}
            sorted_symbols = sorted(symbol_summary.items(), key=lambda x: x[1], reverse=True)
            kpis["best_symbols"] = sorted_symbols[:3]
            kpis["worst_symbols"] = sorted_symbols[-3:] if len(sorted_symbols) >= 3 else sorted_symbols
            
        return kpis
        
    except Exception as e:
        logger.error(f"Failed to calculate daily KPIs: {e}")
        return {"error": str(e)}


async def get_ai_recommendations(kpis: Dict[str, Any]) -> str:
    """
    Get AI-powered improvement recommendations based on daily KPIs
    
    Args:
        kpis: Daily KPIs dictionary
    
    Returns:
        AI-generated recommendations (2-3 actionable insights)
    """
    try:
        # Use DeepSeek (ultra-cheap $0.0001/call)
        from utils.ai_client import get_ai_client
        
        ai_client = get_ai_client()
        
        # Build prompt
        prompt = f"""Analyze today's trading performance and provide 2-3 actionable recommendations:

**Daily Stats:**
- Total PnL: ${kpis.get('total_pnl', 0):.2f}
- Win Rate: {kpis.get('win_rate', 0):.1f}%
- Total Trades: {kpis.get('total_trades', 0)}
- Winning Trades: {kpis.get('winning_trades', 0)}

**Best Performing Symbols:**
{', '.join([f"{sym} (${pnl:.2f})" for sym, pnl in kpis.get('best_symbols', [])[:3]])}

**Worst Performing Symbols:**
{', '.join([f"{sym} (${pnl:.2f})" for sym, pnl in kpis.get('worst_symbols', [])[:3]])}

Provide 2-3 concise, actionable recommendations to improve tomorrow's performance. Focus on:
1. Risk management adjustments
2. Symbol selection optimization
3. Strategy improvements

Keep each recommendation under 50 words."""

        response = await ai_client.complete(
            prompt=prompt,
            max_tokens=200,
            temperature=0.7
        )
        
        if response and "text" in response:
            return response["text"].strip()
        else:
            return "AI recommendations unavailable - focus on high win-rate symbols and tighten stop losses."
            
    except Exception as e:
        logger.error(f"Failed to get AI recommendations: {e}")
        return "AI recommendations unavailable - maintain current strategy and monitor performance."

#!/usr/bin/env python3
"""
Populate Live KPIs Script
==========================
Reads from trades database and populates live_kpis table with historical data.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
from utils.db import _conn, _is_postgres, DB_URL, USE_DB

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("populate_kpis")

def calculate_kpis(positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate KPIs from positions.
    
    Args:
        positions: List of closed positions
        
    Returns:
        Dict with winrate, avg_rr, total_pnl, consec_sl
    """
    if not positions:
        return {
            "winrate": 0.0,
            "avg_rr": 0.0,
            "total_pnl": 0.0,
            "consec_sl": 0,
            "total_trades": 0
        }
    
    winning_trades = [p for p in positions if p.get("pnl", 0) > 0]
    losing_trades = [p for p in positions if p.get("pnl", 0) < 0]
    
    winrate = (len(winning_trades) / len(positions)) * 100 if positions else 0.0
    total_pnl = sum(p.get("pnl", 0) for p in positions)
    
    rr_values = []
    for p in positions:
        pnl = p.get("pnl", 0)
        entry = p.get("entry", 0)
        exit_price = p.get("exit", 0)
        
        if entry and exit_price:
            price_diff = abs(exit_price - entry)
            if price_diff > 0:
                rr = abs(pnl) / (entry * 0.01)
                rr_values.append(rr)
    
    avg_rr = sum(rr_values) / len(rr_values) if rr_values else 0.0
    
    consec_losses = 0
    current_streak = 0
    for p in sorted(positions, key=lambda x: x.get("ts_close", 0)):
        if p.get("pnl", 0) < 0:
            current_streak += 1
            consec_losses = max(consec_losses, current_streak)
        else:
            current_streak = 0
    
    return {
        "winrate": winrate,
        "avg_rr": avg_rr,
        "total_pnl": total_pnl,
        "consec_sl": consec_losses,
        "total_trades": len(positions)
    }

def get_closed_positions(days: int) -> List[Dict[str, Any]]:
    """
    Get closed positions from the last N days.
    
    Args:
        days: Number of days to look back
        
    Returns:
        List of position dicts
    """
    if not USE_DB:
        logger.error("Database is not enabled (USE_DB=0)")
        return []
    
    is_pg = _is_postgres(DB_URL)
    cutoff_ts = (datetime.now() - timedelta(days=days)).timestamp()
    
    positions = []
    with _conn() as con:
        cur = con.cursor()
        
        if is_pg:
            cur.execute("""
                SELECT id, ts_open, ts_close, symbol, side, qty, entry, exit, pnl, status
                FROM positions
                WHERE status = 'CLOSED' 
                  AND ts_close >= to_timestamp(%s)
                ORDER BY ts_close DESC
            """, (cutoff_ts,))
        else:
            cur.execute("""
                SELECT id, ts_open, ts_close, symbol, side, qty, entry, exit, pnl, status
                FROM positions
                WHERE status = 'CLOSED' 
                  AND ts_close >= ?
                ORDER BY ts_close DESC
            """, (cutoff_ts,))
        
        rows = cur.fetchall()
        for row in rows:
            positions.append({
                "id": row[0],
                "ts_open": row[1],
                "ts_close": row[2],
                "symbol": row[3],
                "side": row[4],
                "qty": row[5],
                "entry": row[6],
                "exit": row[7],
                "pnl": row[8],
                "status": row[9]
            })
    
    return positions

def insert_or_update_kpi(day: str, kpis_7d: Dict[str, Any], kpis_30d: Dict[str, Any]):
    """
    Insert or update KPI for a specific day.
    
    Args:
        day: Date string (YYYY-MM-DD)
        kpis_7d: 7-day KPIs
        kpis_30d: 30-day KPIs
    """
    if not USE_DB:
        logger.error("Database is not enabled (USE_DB=0)")
        return
    
    is_pg = _is_postgres(DB_URL)
    
    with _conn() as con:
        cur = con.cursor()
        
        if is_pg:
            cur.execute("""
                INSERT INTO live_kpis (day, winrate_7d, winrate_30d, exp_rr_30d, dd_7d, consec_sl, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (day) 
                DO UPDATE SET 
                    winrate_7d = EXCLUDED.winrate_7d,
                    winrate_30d = EXCLUDED.winrate_30d,
                    exp_rr_30d = EXCLUDED.exp_rr_30d,
                    dd_7d = EXCLUDED.dd_7d,
                    consec_sl = EXCLUDED.consec_sl,
                    updated_at = NOW()
            """, (
                day,
                kpis_7d["winrate"],
                kpis_30d["winrate"],
                kpis_30d["avg_rr"],
                abs(kpis_7d["total_pnl"]) if kpis_7d["total_pnl"] < 0 else 0.0,
                max(kpis_7d["consec_sl"], kpis_30d["consec_sl"])
            ))
        else:
            cur.execute("""
                INSERT OR REPLACE INTO live_kpis 
                (day, winrate_7d, winrate_30d, exp_rr_30d, dd_7d, consec_sl, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
            """, (
                day,
                kpis_7d["winrate"],
                kpis_30d["winrate"],
                kpis_30d["avg_rr"],
                abs(kpis_7d["total_pnl"]) if kpis_7d["total_pnl"] < 0 else 0.0,
                max(kpis_7d["consec_sl"], kpis_30d["consec_sl"])
            ))
        
        if not is_pg:
            con.commit()
        
        logger.info(f"Updated KPIs for {day}: Win%[7d]={kpis_7d['winrate']:.1f}%, Win%[30d]={kpis_30d['winrate']:.1f}%")

def populate_kpis():
    """
    Main function to populate KPIs from historical trades.
    """
    logger.info("Starting KPI population from historical trades...")
    
    positions_7d = get_closed_positions(7)
    positions_30d = get_closed_positions(30)
    
    logger.info(f"Found {len(positions_7d)} positions in last 7 days")
    logger.info(f"Found {len(positions_30d)} positions in last 30 days")
    
    if not positions_7d and not positions_30d:
        logger.warning("No closed positions found. Nothing to populate.")
        return
    
    kpis_7d = calculate_kpis(positions_7d)
    kpis_30d = calculate_kpis(positions_30d)
    
    logger.info(f"7d KPIs: Win%={kpis_7d['winrate']:.1f}%, RR={kpis_7d['avg_rr']:.2f}, P&L={kpis_7d['total_pnl']:.2f}, ConsecSL={kpis_7d['consec_sl']}")
    logger.info(f"30d KPIs: Win%={kpis_30d['winrate']:.1f}%, RR={kpis_30d['avg_rr']:.2f}, P&L={kpis_30d['total_pnl']:.2f}, ConsecSL={kpis_30d['consec_sl']}")
    
    today = datetime.now().date().isoformat()
    insert_or_update_kpi(today, kpis_7d, kpis_30d)
    
    logger.info("KPI population completed successfully!")

if __name__ == "__main__":
    try:
        populate_kpis()
    except Exception as e:
        logger.error(f"Failed to populate KPIs: {e}", exc_info=True)
        exit(1)

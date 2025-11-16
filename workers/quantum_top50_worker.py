#!/usr/bin/env python3
# workers/quantum_top50_worker.py
"""
Quantum TOP 50 Worker
=====================
Dynamic symbol filter with musical chairs - only TOP 50 symbols can trade.
Runs every 8-15 minutes based on market volatility.

Features:
- Smart scanning (120 candidates vs 538 full scan) - 77% efficiency
- Multi-factor scoring (volume, liquidity, volatility)
- Dynamic GRID approval (TOP 10-30)
- Tiered GRID system (Platinum/Gold/Silver/Bronze)
- Garbage detection & auto-blacklist
- Redis + Database persistence
"""

import os
import time
import logging
import asyncio
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("quantum_top50_worker")

try:
    from utils.smart_top50_scanner import get_smart_scanner
    from utils.dynamic_grid_approver import get_grid_approver
    from utils.garbage_detector import get_garbage_detector
    from utils.binance_client import get_client
    from utils.redis_client import get_redis
    from utils.db import _conn, _is_postgres, DB_URL
except Exception as e:
    logger.error(f"Failed to import dependencies: {e}")
    get_smart_scanner = None
    get_grid_approver = None
    get_garbage_detector = None
    get_client = None
    get_redis = None


def calculate_next_scan_interval() -> int:
    volatility_level = get_market_volatility_level()
    
    intervals = {
        'EXTREME': 480,
        'HIGH': 600,
        'MODERATE': 720,
        'STABLE': 900
    }
    
    interval = intervals.get(volatility_level, 720)
    logger.info(f"Market volatility: {volatility_level} → Next scan in {interval}s ({interval/60:.1f} min)")
    return interval


def get_market_volatility_level() -> str:
    if not get_client:
        return 'MODERATE'
    
    try:
        client = get_client()
        ticker = client.futures_ticker(symbol='BTCUSDT')
        price_change_pct = abs(float(ticker.get('priceChangePercent', 0)))
        
        if price_change_pct > 8.0:
            return 'EXTREME'
        elif price_change_pct > 5.0:
            return 'HIGH'
        elif price_change_pct > 2.0:
            return 'MODERATE'
        else:
            return 'STABLE'
    except Exception as e:
        logger.warning(f"Failed to get volatility: {e}")
        return 'MODERATE'


def save_top50_to_redis(symbols: list, redis_client):
    try:
        import json
        
        # Save as JSON (backward compatibility)
        redis_client.setex(
            "top50:approved_list",
            3600,
            json.dumps(symbols)
        )
        
        # 🔧 FIX: Save as SET for Zero Tolerance Filter (atomic update with pipeline)
        pipe = redis_client.pipeline()
        pipe.delete("top50:symbols")  # Clear old data
        if symbols:
            pipe.sadd("top50:symbols", *symbols)  # Add all symbols to SET
        pipe.expire("top50:symbols", 3600)  # Expire in 1h
        pipe.execute()
        
        logger.info(f"✅ Saved TOP 50 to Redis (JSON + SET, {len(symbols)} symbols, expires in 1h)")
    except Exception as e:
        logger.error(f"Failed to save TOP 50 to Redis: {e}")


def save_top50_to_database(symbols_with_scores: list, scan_timestamp):
    try:
        with _conn() as con:
            if not con:
                return
            
            cur = con.cursor()
            is_pg = _is_postgres(DB_URL)
            
            for i, score_obj in enumerate(symbols_with_scores):
                rank = i + 1
                if is_pg:
                    cur.execute("""
                        INSERT INTO top_50_snapshots
                        (scan_timestamp, symbol, rank, total_score, volume_24h, liquidity, volatility_pct)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        scan_timestamp,
                        score_obj.symbol,
                        rank,
                        score_obj.total_score,
                        score_obj.volume_24h,
                        score_obj.liquidity,
                        score_obj.volatility_score
                    ))
                else:
                    cur.execute("""
                        INSERT INTO top_50_snapshots
                        (scan_timestamp, symbol, rank, total_score, volume_24h, liquidity, volatility_pct)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        scan_timestamp.timestamp(),
                        score_obj.symbol,
                        rank,
                        score_obj.total_score,
                        score_obj.volume_24h,
                        score_obj.liquidity,
                        score_obj.volatility_score
                    ))
            
            if not is_pg:
                con.commit()
        
        logger.info(f"✅ Saved TOP 50 snapshot to database")
    except Exception as e:
        logger.error(f"Failed to save TOP 50 to database: {e}")


def save_grid_to_database(grid_symbols_with_scores: list, scan_timestamp):
    try:
        with _conn() as con:
            if not con:
                return
            
            cur = con.cursor()
            is_pg = _is_postgres(DB_URL)
            
            for i, score_obj in enumerate(grid_symbols_with_scores):
                rank = i + 1
                if is_pg:
                    cur.execute("""
                        INSERT INTO grid_snapshot_symbols
                        (scan_timestamp, symbol, rank, tier, grid_score, volume_24h, liquidity, atr_pct, spread_bps)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        scan_timestamp,
                        score_obj.symbol,
                        rank,
                        score_obj.tier,
                        score_obj.grid_score,
                        score_obj.volume_24h,
                        score_obj.liquidity,
                        score_obj.atr_pct,
                        score_obj.spread_bps
                    ))
                else:
                    cur.execute("""
                        INSERT INTO grid_snapshot_symbols
                        (scan_timestamp, symbol, rank, tier, grid_score, volume_24h, liquidity, atr_pct, spread_bps)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        scan_timestamp.timestamp(),
                        score_obj.symbol,
                        rank,
                        score_obj.tier,
                        score_obj.grid_score,
                        score_obj.volume_24h,
                        score_obj.liquidity,
                        score_obj.atr_pct,
                        score_obj.spread_bps
                    ))
            
            if not is_pg:
                con.commit()
        
        logger.info(f"✅ Saved GRID snapshot to database")
    except Exception as e:
        logger.error(f"Failed to save GRID to database: {e}")


def run_scan_cycle():
    logger.info("🔍 Starting Quantum TOP 50 scan cycle...")
    
    scanner = get_smart_scanner() if get_smart_scanner else None
    approver = get_grid_approver() if get_grid_approver else None
    detector = get_garbage_detector() if get_garbage_detector else None
    redis_client = get_redis() if get_redis else None
    
    if not scanner:
        logger.error("SmartTop50Scanner not available")
        return
    
    scan_timestamp = datetime.utcnow()
    
    top_50_symbols = scanner.calculate_optimized_top_50()
    
    if not top_50_symbols:
        logger.warning("No TOP 50 symbols found!")
        return
    
    if redis_client:
        save_top50_to_redis(top_50_symbols, redis_client)
    
    if approver:
        grid_approved = approver.calculate_grid_approved_list(top_50_symbols)
        logger.info(f"GRID approved: {len(grid_approved)} symbols")
    
    if detector:
        garbage_found = detector.scan_for_garbage(top_50_symbols)
        if garbage_found:
            logger.warning(f"💀 Garbage detected: {len(garbage_found)} symbols blacklisted")
    
    logger.info(
        f"✅ Scan cycle complete | "
        f"TOP 50: {len(top_50_symbols)} symbols | "
        f"Next scan in {calculate_next_scan_interval()/60:.1f} min"
    )


def main():
    logger.info("🚀 Quantum TOP 50 Worker started")
    logger.info("Dynamic scheduler: 8-15 min intervals based on volatility")
    
    try:
        from utils.db import init
        init()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning(f"Database init failed: {e}")
    
    while True:
        try:
            run_scan_cycle()
            
            interval = calculate_next_scan_interval()
            logger.info(f"😴 Sleeping for {interval}s ({interval/60:.1f} min)...")
            time.sleep(interval)
            
        except KeyboardInterrupt:
            logger.info("Shutting down gracefully...")
            break
        except Exception as e:
            logger.error(f"Error in scan cycle: {e}", exc_info=True)
            logger.info("Retrying in 60s...")
            time.sleep(60)


if __name__ == "__main__":
    main()

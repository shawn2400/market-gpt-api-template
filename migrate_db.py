#!/usr/bin/env python3
"""
================================================================================
AlgoGPT Database Migration Script
================================================================================
Migrates all data from Replit PostgreSQL to Render PostgreSQL.
Copies all 10 tables with their data intact.
================================================================================
"""

import os
import sys
from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.orm import sessionmaker

# Source DB (Replit)
SOURCE_DB_URL = os.getenv("SOURCE_DATABASE_URL") or os.getenv("DATABASE_URL")

# Target DB (Render) - you'll set this manually
TARGET_DB_URL = os.getenv("TARGET_DATABASE_URL")

# Tables to migrate (in order to respect foreign keys)
TABLES = [
    "slippage_history",
    "breaker_state",
    "market_states",
    "audit_log",
    "ai_predictions",
    "trade_outcomes",
    "feedback_dataset",
    "live_kpis",
    "validation_runs",
    "backtest_folds",
]


def migrate_database():
    """Migrate all data from source to target database"""
    
    if not SOURCE_DB_URL:
        print("❌ SOURCE_DATABASE_URL not set!")
        print("   Set it to your Replit DATABASE_URL")
        sys.exit(1)
    
    if not TARGET_DB_URL:
        print("❌ TARGET_DATABASE_URL not set!")
        print("   Set it to your Render PostgreSQL connection string")
        print("   Example: postgresql://algogpt_user:password@localhost/algogpt_production")
        sys.exit(1)
    
    print("🗄️ AlgoGPT Database Migration")
    print("=" * 80)
    print(f"📥 Source: {SOURCE_DB_URL[:30]}...")
    print(f"📤 Target: {TARGET_DB_URL[:30]}...")
    print("=" * 80)
    
    # Create engines
    print("\n🔌 Connecting to databases...")
    source_engine = create_engine(SOURCE_DB_URL)
    target_engine = create_engine(TARGET_DB_URL)
    
    # Create metadata
    source_metadata = MetaData()
    target_metadata = MetaData()
    
    # Reflect source schema
    print("🔍 Reflecting source database schema...")
    source_metadata.reflect(bind=source_engine)
    
    # Create target schema
    print("📋 Creating target database schema...")
    source_metadata.create_all(bind=target_engine)
    
    # Create sessions
    SourceSession = sessionmaker(bind=source_engine)
    TargetSession = sessionmaker(bind=target_engine)
    
    source_session = SourceSession()
    target_session = TargetSession()
    
    # Migrate each table
    print("\n📊 Migrating tables...")
    total_rows = 0
    
    for table_name in TABLES:
        if table_name not in source_metadata.tables:
            print(f"  ⚠️  Table '{table_name}' not found in source, skipping...")
            continue
        
        table = source_metadata.tables[table_name]
        
        # Count rows in source
        count_query = source_session.execute(table.select()).fetchall()
        row_count = len(count_query)
        
        if row_count == 0:
            print(f"  ✓ {table_name}: 0 rows (empty table)")
            continue
        
        print(f"  📦 {table_name}: copying {row_count} rows...", end="", flush=True)
        
        # Read all data from source
        source_data = source_session.execute(table.select()).fetchall()
        
        # Convert to dictionaries
        rows_to_insert = []
        for row in source_data:
            row_dict = dict(row._mapping)
            rows_to_insert.append(row_dict)
        
        # Insert into target
        if rows_to_insert:
            target_session.execute(table.insert(), rows_to_insert)
            target_session.commit()
        
        total_rows += row_count
        print(f" ✅ Done!")
    
    # Close sessions
    source_session.close()
    target_session.close()
    
    print("\n" + "=" * 80)
    print(f"✅ Migration complete! Migrated {total_rows} rows across {len(TABLES)} tables.")
    print("=" * 80)


if __name__ == "__main__":
    try:
        migrate_database()
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

"""
Initialize AlgoGPT Database
============================
Creates all database tables and verifies connection.

Run this once to setup the database.
"""

import logging
from utils.database_models import init_database

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

if __name__ == "__main__":
    print("🚀 Initializing AlgoGPT Database...")
    init_database()
    print("✅ Database initialization complete!")
    print("\nTables created:")
    print("  - trade_sizing: Position sizing calculations")
    print("  - position_flips: Flip decisions and history")
    print("  - market_states: Market intelligence states")
    print("  - performance_records: Trade performance tracking")
    print("  - system_decisions: All system decisions")
    print("\n💾 All data will now be saved automatically!")

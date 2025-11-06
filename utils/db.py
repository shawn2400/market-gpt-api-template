# utils/db.py
import os, sqlite3, json, time
from contextlib import contextmanager
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger("algogpt.db")

# CRITICAL FIX: Override DATABASE_URL if pointing to disabled endpoint
_db_url_env = os.getenv("DATABASE_URL", "sqlite:////app/data/algogpt.db")
if "ep-cool-tooth-a5dlnc71" in _db_url_env:
    logger.warning("🔧 DATABASE_URL pointing to DISABLED endpoint, overriding with ACTIVE endpoint")
    DB_URL = "postgresql://neondb_owner:npg_8zKsmVwMLZ0u@ep-spring-silence-ag9wyuvd-pooler.c-2.eu-central-1.aws.neon.tech/neondb?channel_binding=require&sslmode=require"
    os.environ["DATABASE_URL"] = DB_URL  # Update environment for child processes
    logger.info("✅ DATABASE_URL overridden: ep-spring-silence-ag9wyuvd (ACTIVE)")
else:
    DB_URL = _db_url_env

USE_DB = os.getenv("USE_DB","1").lower() in ("1","true","yes","on")

def _is_postgres(url: str) -> bool:
    """Check if database URL is PostgreSQL"""
    return url.startswith("postgresql://") or url.startswith("postgres://")

def _path_from_url(url: str) -> str:
    # sqlite:////abs/path.db  -> /abs/path.db
    return url.replace("sqlite:////", "/")

@contextmanager
def _conn():
    """Database connection context manager - supports both SQLite and PostgreSQL"""
    if not USE_DB:
        yield None
        return
    
    if _is_postgres(DB_URL):
        # PostgreSQL connection
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            raise ImportError("psycopg2 required for PostgreSQL. Install with: pip install psycopg2-binary")
        
        con = psycopg2.connect(DB_URL)
        con.autocommit = True
        try:
            yield con
        finally:
            con.close()
    else:
        # SQLite connection
        path = _path_from_url(DB_URL)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        con = sqlite3.connect(path, isolation_level=None)
        try:
            yield con
        finally:
            con.close()

def init():
    """Initialize database schema - supports both SQLite and PostgreSQL"""
    if not USE_DB: return
    
    is_pg = _is_postgres(DB_URL)
    
    with _conn() as con:
        cur = con.cursor()
        
        if is_pg:
            _init_postgres(cur)
        else:
            _init_sqlite(cur)
        
        if not is_pg:
            con.commit()

def _init_postgres(cur):
    """Initialize PostgreSQL schema"""
    # Existing tables
    cur.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
          id VARCHAR PRIMARY KEY,
          ts TIMESTAMP NOT NULL,
          symbol VARCHAR NOT NULL,
          side VARCHAR NOT NULL,
          entry FLOAT NOT NULL,
          sl FLOAT NOT NULL,
          tp1 FLOAT,
          tp2 FLOAT,
          tp3 FLOAT,
          approved INTEGER DEFAULT 0,
          note TEXT
        );
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
          id VARCHAR PRIMARY KEY,
          ts TIMESTAMP NOT NULL,
          symbol VARCHAR NOT NULL,
          side VARCHAR NOT NULL,
          qty FLOAT NOT NULL,
          price FLOAT,
          position_side VARCHAR,
          source VARCHAR,
          raw JSONB
        );
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS positions (
          id VARCHAR PRIMARY KEY,
          ts_open TIMESTAMP NOT NULL,
          ts_close TIMESTAMP,
          symbol VARCHAR NOT NULL,
          side VARCHAR NOT NULL,
          qty FLOAT NOT NULL,
          entry FLOAT,
          exit FLOAT,
          pnl FLOAT,
          status VARCHAR
        );
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tf_snapshots (
          id SERIAL PRIMARY KEY,
          symbol VARCHAR NOT NULL,
          interval VARCHAR NOT NULL,
          timestamp TIMESTAMP NOT NULL,
          indicators JSONB NOT NULL,
          alignment_status VARCHAR,
          created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tf_snapshots_symbol_interval ON tf_snapshots(symbol, interval);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tf_snapshots_timestamp ON tf_snapshots(timestamp);")
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bt_runs (
          id VARCHAR PRIMARY KEY,
          strategy VARCHAR NOT NULL,
          start_date VARCHAR NOT NULL,
          end_date VARCHAR NOT NULL,
          folds INTEGER NOT NULL,
          created_at TIMESTAMP DEFAULT NOW(),
          status VARCHAR DEFAULT 'running',
          summary_json JSONB
        );
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bt_results (
          id SERIAL PRIMARY KEY,
          bt_run_id VARCHAR NOT NULL,
          symbol VARCHAR,
          regime VARCHAR,
          winrate FLOAT,
          avg_rr FLOAT,
          expectancy FLOAT,
          max_dd FLOAT,
          sample_n INTEGER,
          FOREIGN KEY (bt_run_id) REFERENCES bt_runs(id)
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bt_results_run_id ON bt_results(bt_run_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bt_results_symbol_regime ON bt_results(symbol, regime);")
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS live_kpis (
          id SERIAL PRIMARY KEY,
          day VARCHAR NOT NULL UNIQUE,
          winrate_7d FLOAT,
          winrate_30d FLOAT,
          exp_rr_30d FLOAT,
          dd_7d FLOAT,
          consec_sl INTEGER,
          updated_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_live_kpis_day ON live_kpis(day);")
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS blocks_log (
          id SERIAL PRIMARY KEY,
          reason VARCHAR NOT NULL,
          ctx_json JSONB,
          created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_blocks_log_created_at ON blocks_log(created_at);")
    
    # NEW: AI Performance Tracking Tables
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_predictions (
          id SERIAL PRIMARY KEY,
          prediction_id VARCHAR UNIQUE NOT NULL,
          timestamp TIMESTAMP NOT NULL,
          symbol VARCHAR NOT NULL,
          ai_model VARCHAR NOT NULL,
          confidence FLOAT NOT NULL,
          prediction JSONB NOT NULL,
          regime VARCHAR NOT NULL,
          features JSONB,
          created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_predictions_model_regime_ts ON ai_predictions(ai_model, regime, timestamp);")
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trade_outcomes (
          id SERIAL PRIMARY KEY,
          outcome_id VARCHAR UNIQUE NOT NULL,
          prediction_id VARCHAR REFERENCES ai_predictions(prediction_id),
          timestamp TIMESTAMP NOT NULL,
          symbol VARCHAR NOT NULL,
          pnl_usd FLOAT NOT NULL,
          pnl_pct FLOAT NOT NULL,
          rr_achieved FLOAT NOT NULL,
          time_in_trade_minutes INTEGER NOT NULL,
          exit_reason VARCHAR NOT NULL,
          was_successful BOOLEAN NOT NULL,
          created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_trade_outcomes_pred_success_ts ON trade_outcomes(prediction_id, was_successful, timestamp);")
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS feedback_dataset (
          id SERIAL PRIMARY KEY,
          trade_id VARCHAR,
          symbol VARCHAR NOT NULL,
          ai_model VARCHAR NOT NULL,
          prediction JSONB NOT NULL,
          outcome JSONB NOT NULL,
          label VARCHAR NOT NULL,
          features JSONB,
          regime VARCHAR,
          created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_feedback_model_regime_label ON feedback_dataset(ai_model, regime, label);")
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS slippage_history (
          symbol VARCHAR NOT NULL,
          side VARCHAR NOT NULL,
          vol_regime VARCHAR NOT NULL,
          avg_slippage_bps FLOAT NOT NULL,
          sample_count INTEGER NOT NULL,
          last_updated TIMESTAMP DEFAULT NOW(),
          PRIMARY KEY (symbol, side, vol_regime)
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_slippage_symbol ON slippage_history(symbol);")
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS breaker_state (
          id SERIAL PRIMARY KEY,
          daily_dd FLOAT NOT NULL,
          daily_dd_peak FLOAT NOT NULL,
          consec_losses INTEGER NOT NULL,
          last_reset DATE NOT NULL,
          paused BOOLEAN DEFAULT FALSE,
          pause_reason VARCHAR,
          created_at TIMESTAMP DEFAULT NOW(),
          updated_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_breaker_last_reset ON breaker_state(last_reset);")
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
          id SERIAL PRIMARY KEY,
          timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
          user_id VARCHAR,
          action VARCHAR NOT NULL,
          entity_type VARCHAR NOT NULL,
          entity_id VARCHAR,
          changes JSONB,
          ip_address VARCHAR,
          success BOOLEAN DEFAULT TRUE,
          error TEXT,
          created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);")
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_states (
          id SERIAL PRIMARY KEY,
          symbol VARCHAR NOT NULL,
          regime VARCHAR NOT NULL,
          mood VARCHAR NOT NULL,
          volatility VARCHAR NOT NULL,
          trend_strength FLOAT NOT NULL,
          strategy VARCHAR NOT NULL,
          min_rr FLOAT NOT NULL,
          min_quality FLOAT NOT NULL,
          indicators JSONB,
          created_at TIMESTAMP DEFAULT NOW(),
          updated_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_market_states_symbol ON market_states(symbol);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_market_states_updated_at ON market_states(updated_at);")

def _init_sqlite(cur):
    """Initialize SQLite schema"""
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS alerts (
          id TEXT PRIMARY KEY,
          ts REAL NOT NULL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          entry REAL NOT NULL,
          sl REAL NOT NULL,
          tp1 REAL,
          tp2 REAL,
          tp3 REAL,
          approved INTEGER DEFAULT 0,
          note TEXT
        );

        CREATE TABLE IF NOT EXISTS orders (
          id TEXT PRIMARY KEY,
          ts REAL NOT NULL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          qty REAL NOT NULL,
          price REAL,
          position_side TEXT,
          source TEXT,
          raw TEXT
        );

        CREATE TABLE IF NOT EXISTS positions (
          id TEXT PRIMARY KEY,
          ts_open REAL NOT NULL,
          ts_close REAL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          qty REAL NOT NULL,
          entry REAL,
          exit REAL,
          pnl REAL,
          status TEXT
        );

        CREATE TABLE IF NOT EXISTS tf_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          symbol TEXT NOT NULL,
          interval TEXT NOT NULL,
          timestamp REAL NOT NULL,
          indicators TEXT NOT NULL,
          alignment_status TEXT,
          created_at REAL DEFAULT (strftime('%s', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_tf_snapshots_symbol_interval ON tf_snapshots(symbol, interval);
        CREATE INDEX IF NOT EXISTS idx_tf_snapshots_timestamp ON tf_snapshots(timestamp);

        CREATE TABLE IF NOT EXISTS bt_runs (
          id TEXT PRIMARY KEY,
          strategy TEXT NOT NULL,
          start_date TEXT NOT NULL,
          end_date TEXT NOT NULL,
          folds INTEGER NOT NULL,
          created_at REAL DEFAULT (strftime('%s', 'now')),
          status TEXT DEFAULT 'running',
          summary_json TEXT
        );

        CREATE TABLE IF NOT EXISTS bt_results (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          bt_run_id TEXT NOT NULL,
          symbol TEXT,
          regime TEXT,
          winrate REAL,
          avg_rr REAL,
          expectancy REAL,
          max_dd REAL,
          sample_n INTEGER,
          FOREIGN KEY (bt_run_id) REFERENCES bt_runs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_bt_results_run_id ON bt_results(bt_run_id);
        CREATE INDEX IF NOT EXISTS idx_bt_results_symbol_regime ON bt_results(symbol, regime);

        CREATE TABLE IF NOT EXISTS live_kpis (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          day TEXT NOT NULL UNIQUE,
          winrate_7d REAL,
          winrate_30d REAL,
          exp_rr_30d REAL,
          dd_7d REAL,
          consec_sl INTEGER,
          updated_at REAL DEFAULT (strftime('%s', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_live_kpis_day ON live_kpis(day);

        CREATE TABLE IF NOT EXISTS blocks_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          reason TEXT NOT NULL,
          ctx_json TEXT,
          created_at REAL DEFAULT (strftime('%s', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_blocks_log_created_at ON blocks_log(created_at);
        
        -- NEW: AI Performance Tracking Tables
        CREATE TABLE IF NOT EXISTS ai_predictions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          prediction_id TEXT UNIQUE NOT NULL,
          timestamp REAL NOT NULL,
          symbol TEXT NOT NULL,
          ai_model TEXT NOT NULL,
          confidence REAL NOT NULL,
          prediction TEXT NOT NULL,
          regime TEXT NOT NULL,
          features TEXT,
          created_at REAL DEFAULT (strftime('%s', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_ai_predictions_model_regime_ts ON ai_predictions(ai_model, regime, timestamp);
        
        CREATE TABLE IF NOT EXISTS trade_outcomes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          outcome_id TEXT UNIQUE NOT NULL,
          prediction_id TEXT,
          timestamp REAL NOT NULL,
          symbol TEXT NOT NULL,
          pnl_usd REAL NOT NULL,
          pnl_pct REAL NOT NULL,
          rr_achieved REAL NOT NULL,
          time_in_trade_minutes INTEGER NOT NULL,
          exit_reason TEXT NOT NULL,
          was_successful INTEGER NOT NULL,
          created_at REAL DEFAULT (strftime('%s', 'now')),
          FOREIGN KEY (prediction_id) REFERENCES ai_predictions(prediction_id)
        );
        CREATE INDEX IF NOT EXISTS idx_trade_outcomes_pred_success_ts ON trade_outcomes(prediction_id, was_successful, timestamp);
        
        CREATE TABLE IF NOT EXISTS feedback_dataset (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          trade_id TEXT,
          symbol TEXT NOT NULL,
          ai_model TEXT NOT NULL,
          prediction TEXT NOT NULL,
          outcome TEXT NOT NULL,
          label TEXT NOT NULL,
          features TEXT,
          regime TEXT,
          created_at REAL DEFAULT (strftime('%s', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_model_regime_label ON feedback_dataset(ai_model, regime, label);
        
        CREATE TABLE IF NOT EXISTS slippage_history (
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          vol_regime TEXT NOT NULL,
          avg_slippage_bps REAL NOT NULL,
          sample_count INTEGER NOT NULL,
          last_updated REAL DEFAULT (strftime('%s', 'now')),
          PRIMARY KEY (symbol, side, vol_regime)
        );
        CREATE INDEX IF NOT EXISTS idx_slippage_symbol ON slippage_history(symbol);
        
        CREATE TABLE IF NOT EXISTS breaker_state (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          daily_dd REAL NOT NULL,
          daily_dd_peak REAL NOT NULL,
          consec_losses INTEGER NOT NULL,
          last_reset TEXT NOT NULL,
          paused INTEGER DEFAULT 0,
          pause_reason TEXT,
          created_at REAL DEFAULT (strftime('%s', 'now')),
          updated_at REAL DEFAULT (strftime('%s', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_breaker_last_reset ON breaker_state(last_reset);
        
        CREATE TABLE IF NOT EXISTS audit_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          timestamp REAL NOT NULL DEFAULT (strftime('%s', 'now')),
          user_id TEXT,
          action TEXT NOT NULL,
          entity_type TEXT NOT NULL,
          entity_id TEXT,
          changes TEXT,
          ip_address TEXT,
          success INTEGER DEFAULT 1,
          error TEXT,
          created_at REAL DEFAULT (strftime('%s', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);
        CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
        
        CREATE TABLE IF NOT EXISTS market_states (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          symbol TEXT NOT NULL,
          regime TEXT NOT NULL,
          mood TEXT NOT NULL,
          volatility TEXT NOT NULL,
          trend_strength REAL NOT NULL,
          strategy TEXT NOT NULL,
          min_rr REAL NOT NULL,
          min_quality REAL NOT NULL,
          indicators TEXT,
          created_at REAL DEFAULT (strftime('%s', 'now')),
          updated_at REAL DEFAULT (strftime('%s', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_market_states_symbol ON market_states(symbol);
        CREATE INDEX IF NOT EXISTS idx_market_states_updated_at ON market_states(updated_at);
    """)
    

def insert_alert(row: Dict[str, Any]):
    if not USE_DB: return
    with _conn() as con:
        cur = con.cursor()
        cur.execute("""INSERT OR REPLACE INTO alerts
          (id, ts, symbol, side, entry, sl, tp1, tp2, tp3, approved, note)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            row.get("id"),
            row.get("ts", time.time()),
            row["symbol"], row["side"], float(row["entry"]), float(row["sl"]),
            row.get("tp1"), row.get("tp2"), row.get("tp3"),
            1 if row.get("approved") else 0,
            row.get("note")
        ))
        con.commit()

def insert_order(row: Dict[str, Any]):
    if not USE_DB: return
    with _conn() as con:
        cur = con.cursor()
        cur.execute("""INSERT OR REPLACE INTO orders
          (id, ts, symbol, side, qty, price, position_side, source, raw)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            row.get("id"),
            row.get("ts", time.time()),
            row["symbol"], row["side"], float(row["qty"]),
            row.get("price"),
            row.get("position_side"),
            row.get("source","system"),
            json.dumps(row.get("raw", {}))
        ))
        con.commit()

def insert_position(row: Dict[str, Any]):
    if not USE_DB: return
    with _conn() as con:
        cur = con.cursor()
        cur.execute("""INSERT OR REPLACE INTO positions
          (id, ts_open, ts_close, symbol, side, qty, entry, exit, pnl, status)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            row.get("id"),
            row.get("ts_open", time.time()),
            row.get("ts_close"),
            row["symbol"], row["side"], float(row["qty"]),
            row.get("entry"), row.get("exit"), row.get("pnl"),
            row.get("status","OPEN")
        ))
        con.commit()

def insert_tf_snapshot(row: Dict[str, Any]):
    """
    Insert multi-timeframe snapshot into database.
    
    Args:
        row: Dict with symbol, interval, timestamp, indicators, alignment_status
    """
    if not USE_DB: return
    with _conn() as con:
        cur = con.cursor()
        cur.execute("""INSERT INTO tf_snapshots
          (symbol, interval, timestamp, indicators, alignment_status)
          VALUES (?, ?, ?, ?, ?)""", (
            row["symbol"],
            row["interval"],
            row.get("timestamp", time.time()),
            json.dumps(row.get("indicators", {})),
            row.get("alignment_status", "UNKNOWN")
        ))
        con.commit()

def upsert_slippage(symbol: str, side: str, vol_regime: str, avg_slippage_bps: float, sample_count: int):
    """
    Insert or update slippage history.
    
    Args:
        symbol: Trading symbol
        side: LONG or SHORT
        vol_regime: LOW, MEDIUM, HIGH
        avg_slippage_bps: Average slippage in basis points
        sample_count: Number of samples
    """
    if not USE_DB: return
    is_pg = _is_postgres(DB_URL)
    
    with _conn() as con:
        cur = con.cursor()
        if is_pg:
            cur.execute("""
                INSERT INTO slippage_history (symbol, side, vol_regime, avg_slippage_bps, sample_count, last_updated)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (symbol, side, vol_regime) 
                DO UPDATE SET 
                    avg_slippage_bps = EXCLUDED.avg_slippage_bps,
                    sample_count = EXCLUDED.sample_count,
                    last_updated = NOW()
            """, (symbol, side, vol_regime, avg_slippage_bps, sample_count))
        else:
            cur.execute("""
                INSERT OR REPLACE INTO slippage_history 
                (symbol, side, vol_regime, avg_slippage_bps, sample_count, last_updated)
                VALUES (?, ?, ?, ?, ?, strftime('%s', 'now'))
            """, (symbol, side, vol_regime, avg_slippage_bps, sample_count))
        if not is_pg:
            con.commit()

def get_slippage(symbol: str, side: str, vol_regime: str) -> Optional[Dict[str, Any]]:
    """
    Get slippage data for a specific symbol/side/regime.
    
    Returns:
        Dict with avg_slippage_bps and sample_count, or None if not found
    """
    if not USE_DB: return None
    is_pg = _is_postgres(DB_URL)
    
    with _conn() as con:
        cur = con.cursor()
        if is_pg:
            cur.execute("""
                SELECT avg_slippage_bps, sample_count, last_updated
                FROM slippage_history
                WHERE symbol = %s AND side = %s AND vol_regime = %s
            """, (symbol, side, vol_regime))
        else:
            cur.execute("""
                SELECT avg_slippage_bps, sample_count, last_updated
                FROM slippage_history
                WHERE symbol = ? AND side = ? AND vol_regime = ?
            """, (symbol, side, vol_regime))
        
        row = cur.fetchone()
        if row:
            return {
                "avg_slippage_bps": row[0],
                "sample_count": row[1],
                "last_updated": row[2]
            }
        return None

def get_all_slippage() -> Dict[str, Any]:
    """
    Get all slippage data.
    
    Returns:
        Dict mapping (symbol, side, vol_regime) to slippage stats
    """
    if not USE_DB: return {}
    is_pg = _is_postgres(DB_URL)
    
    with _conn() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT symbol, side, vol_regime, avg_slippage_bps, sample_count, last_updated
            FROM slippage_history
        """)
        
        result = {}
        for row in cur.fetchall():
            key = f"{row[0]}_{row[1]}_{row[2]}"
            result[key] = {
                "symbol": row[0],
                "side": row[1],
                "vol_regime": row[2],
                "avg_slippage_bps": row[3],
                "sample_count": row[4],
                "last_updated": row[5]
            }
        return result

def save_breaker_state(state: Dict[str, Any]):
    """
    Save circuit breaker state to database.
    
    Args:
        state: Dict with daily_dd, daily_dd_peak, consec_losses, last_reset, paused, pause_reason
    """
    if not USE_DB: return
    is_pg = _is_postgres(DB_URL)
    
    with _conn() as con:
        cur = con.cursor()
        if is_pg:
            cur.execute("""
                INSERT INTO breaker_state 
                (daily_dd, daily_dd_peak, consec_losses, last_reset, paused, pause_reason, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """, (
                state.get("daily_dd", 0.0),
                state.get("daily_dd_peak", 0.0),
                state.get("consec_losses", 0),
                state.get("last_reset"),
                state.get("paused", False),
                state.get("pause_reason", "")
            ))
        else:
            cur.execute("""
                INSERT INTO breaker_state 
                (daily_dd, daily_dd_peak, consec_losses, last_reset, paused, pause_reason, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
            """, (
                state.get("daily_dd", 0.0),
                state.get("daily_dd_peak", 0.0),
                state.get("consec_losses", 0),
                state.get("last_reset"),
                1 if state.get("paused", False) else 0,
                state.get("pause_reason", "")
            ))
        if not is_pg:
            con.commit()

def get_latest_breaker_state() -> Optional[Dict[str, Any]]:
    """
    Get the most recent circuit breaker state.
    
    Returns:
        Dict with breaker state or None if not found
    """
    if not USE_DB: return None
    is_pg = _is_postgres(DB_URL)
    
    with _conn() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, daily_dd, daily_dd_peak, consec_losses, last_reset, paused, pause_reason, created_at, updated_at
            FROM breaker_state
            ORDER BY id DESC
            LIMIT 1
        """)
        
        row = cur.fetchone()
        if row:
            return {
                "id": row[0],
                "daily_dd": row[1],
                "daily_dd_peak": row[2],
                "consec_losses": row[3],
                "last_reset": row[4],
                "paused": bool(row[5]) if is_pg else bool(row[5]),
                "pause_reason": row[6] or "",
                "created_at": row[7],
                "updated_at": row[8]
            }
        return None

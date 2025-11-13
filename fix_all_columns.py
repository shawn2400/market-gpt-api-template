import psycopg2
import os

def fix_all_columns():
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL not found")
        return
    
    try:
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        # הוסף את כל העמודות החסרות
        alter_table_sql = """
        ALTER TABLE breaker_state 
        ADD COLUMN IF NOT EXISTS pause_reason TEXT,
        ADD COLUMN IF NOT EXISTS daily_loss_amount DECIMAL(15, 2) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS breaker_type VARCHAR(50) DEFAULT 'daily_loss',
        ADD COLUMN IF NOT EXISTS triggered BOOLEAN DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS trigger_reason TEXT,
        ADD COLUMN IF NOT EXISTS triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
        """
        
        cursor.execute(alter_table_sql)
        conn.commit()
        print("✅ Added all missing columns to breaker_state table!")
        
        # בדוק את מבנה הטבלה הסופי
        cursor.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns 
        WHERE table_name = 'breaker_state' 
        ORDER BY ordinal_position;
        """)
        
        columns = cursor.fetchall()
        print("📊 FINAL breaker_state table structure:")
        for col in columns:
            print(f"  - {col[0]}: {col[1]} ({'NULL' if col[2] == 'YES' else 'NOT NULL'})")
            
    except Exception as e:
        print(f"❌ Error adding columns: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    fix_all_columns()

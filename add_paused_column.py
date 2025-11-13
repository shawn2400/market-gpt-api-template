import psycopg2
import os

def add_paused_column():
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL not found")
        return
    
    try:
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        # הוסף את עמודת paused
        alter_table_sql = """
        ALTER TABLE breaker_state 
        ADD COLUMN IF NOT EXISTS paused BOOLEAN DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS panic_close_triggered BOOLEAN DEFAULT FALSE;
        """
        
        cursor.execute(alter_table_sql)
        conn.commit()
        print("✅ Added 'paused' and 'panic_close_triggered' columns to breaker_state table!")
        
        # בדוק את מבנה הטבלה
        cursor.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'breaker_state' 
        ORDER BY ordinal_position;
        """)
        
        columns = cursor.fetchall()
        print("📊 breaker_state table structure:")
        for col in columns:
            print(f"  - {col[0]}: {col[1]}")
            
    except Exception as e:
        print(f"❌ Error adding column: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    add_paused_column()

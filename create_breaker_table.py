import psycopg2
import os

def create_breaker_table():
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL not found")
        return
    
    try:
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS breaker_state (
            id SERIAL PRIMARY KEY,
            breaker_type VARCHAR(50) NOT NULL,
            triggered BOOLEAN DEFAULT FALSE,
            trigger_reason TEXT,
            triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            daily_loss_amount DECIMAL(15, 2) DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        cursor.execute(create_table_sql)
        conn.commit()
        print("✅ breaker_state table created successfully!")
        
        # בדוק שהטבלה נוצרה
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_name = 'breaker_state';")
        result = cursor.fetchone()
        
        if result:
            print("✅ Table verification: breaker_state exists")
        else:
            print("❌ Table verification failed")
            
    except Exception as e:
        print(f"❌ Error creating table: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    create_breaker_table()

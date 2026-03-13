import sqlite3
import os

DB_PATH = 'market.db'

def migrate():
    if not os.path.exists(DB_PATH):
        print("Database file not found. Please run database.py first.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check current columns in users
    cursor.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]
    
    needed_columns = [
        ('city', 'TEXT'),
        ('state', 'TEXT'),
        ('district', 'TEXT'),
        ('pincode', 'TEXT'),
        ('latitude', 'REAL'),
        ('longitude', 'REAL'),
        ('is_verified', 'INTEGER DEFAULT 0')
    ]
    
    for col_name, col_type in needed_columns:
        if col_name not in columns:
            print(f"Adding column {col_name} to users table...")
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            except Exception as e:
                print(f"Error adding {col_name} to users: {e}")
                
    # Check crops table for all new fields
    cursor.execute("PRAGMA table_info(crops)")
    crop_columns = [row[1] for row in cursor.fetchall()]
    
    needed_crop_columns = [
        ('image_url', 'TEXT'),
        ('category', 'TEXT'),
        ('harvest_date', 'TEXT'),
        ('village', 'TEXT'),
        ('state', 'TEXT'),
        ('district', 'TEXT'),
        ('pincode', 'TEXT'),
        ('quality', 'TEXT'),
        ('quality_proof', 'TEXT')
    ]
    
    for col_name, col_type in needed_crop_columns:
        if col_name not in crop_columns:
            print(f"Adding column {col_name} to crops table...")
            try:
                cursor.execute(f"ALTER TABLE crops ADD COLUMN {col_name} {col_type}")
            except Exception as e:
                print(f"Error adding {col_name} to crops: {e}")

    # Check for reviews table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reviews'")
    if not cursor.fetchone():
        print("Creating reviews table...")
        cursor.execute('''
        CREATE TABLE reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            customer_id INTEGER NOT NULL,
            farmer_id INTEGER NOT NULL,
            rating INTEGER CHECK(rating >= 1 AND rating <= 5),
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders (id),
            FOREIGN KEY (customer_id) REFERENCES users (id),
            FOREIGN KEY (farmer_id) REFERENCES users (id)
        )
        ''')

    conn.commit()
    conn.close()
    print("Migration completed successfully.")

if __name__ == '__main__':
    migrate()

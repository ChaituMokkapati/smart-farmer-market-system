import sqlite3
import os

DB_PATH = 'market.db'

def migrate():
    if not os.path.exists(DB_PATH):
        print("Database does not exist.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Add columns to 'orders' table
    orders_cols = [
        ('estimated_delivery', 'TEXT'),
        ('current_location', 'TEXT')
    ]
    for col, col_type in orders_cols:
        try:
            cursor.execute(f"ALTER TABLE orders ADD COLUMN {col} {col_type}")
            print(f"Added {col} to orders")
        except sqlite3.OperationalError:
            print(f"{col} already exists in orders")

    # Order Updates Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS order_updates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        update_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        location TEXT,
        FOREIGN KEY (order_id) REFERENCES orders (id)
    )
    ''')
    print("Created order_updates table")

    conn.commit()
    conn.close()

if __name__ == '__main__':
    migrate()

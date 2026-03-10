import sqlite3
import os

DB_PATH = 'market.db'

def migrate():
    if not os.path.exists(DB_PATH):
        print("Database does not exist or has a different name.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # User Table
    users_cols = [
        ('state', 'TEXT'),
        ('district', 'TEXT'),
        ('pincode', 'TEXT')
    ]
    for col, col_type in users_cols:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
            print(f"Added {col} to users")
        except sqlite3.OperationalError:
            print(f"{col} already exists in users")

    # Crops Table
    crops_cols = [
        ('category', 'TEXT'),
        ('harvest_date', 'TEXT'),
        ('state', 'TEXT'),
        ('district', 'TEXT'),
        ('village', 'TEXT'),
        ('pincode', 'TEXT'),
        ('quality', 'TEXT'),
        ('quality_proof', 'TEXT')
    ]
    for col, col_type in crops_cols:
        try:
            cursor.execute(f"ALTER TABLE crops ADD COLUMN {col} {col_type}")
            print(f"Added {col} to crops")
        except sqlite3.OperationalError:
            print(f"{col} already exists in crops")

    conn.commit()
    conn.close()

if __name__ == '__main__':
    migrate()

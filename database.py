import sqlite3
import os

DB_PATH = 'market.db'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # User Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL, -- 'farmer', 'customer', 'admin'
        full_name TEXT,
        contact TEXT,
        city TEXT,
        state TEXT,
        district TEXT,
        pincode TEXT,
        latitude REAL,
        longitude REAL,
        is_verified INTEGER DEFAULT 0 -- 0: No, 1: Yes
    )
    ''')
    
    # Crops Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS crops (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        farmer_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        category TEXT,
        quantity REAL NOT NULL,
        price REAL NOT NULL,
        harvest_date TEXT,
        state TEXT,
        district TEXT,
        village TEXT,
        pincode TEXT,
        description TEXT,
        image_url TEXT,
        quality TEXT,
        quality_proof TEXT,
        FOREIGN KEY (farmer_id) REFERENCES users (id)
    )
    ''')
    
    # Orders Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        crop_id INTEGER NOT NULL,
        quantity REAL NOT NULL,
        total_price REAL NOT NULL,
        status TEXT DEFAULT 'pending', -- 'pending', 'paid', 'shipped', 'completed', 'cancelled'
        order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES users (id),
        FOREIGN KEY (crop_id) REFERENCES crops (id)
    )
    ''')

    # Reviews Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reviews (
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
    
    # Create Default Admin if not exists
    cursor.execute("SELECT * FROM users WHERE role = 'admin'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)", 
                       ('admin', 'admin123', 'admin', 'System Administrator'))
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")

import os
import sqlite3

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")


def load_runtime_env():
    preserve_env = (os.getenv("PRESERVE_ENV_VARS") or "").strip().lower() in {"1", "true", "yes", "on"}
    load_dotenv(ENV_PATH, override=not preserve_env)


def get_db_path():
    load_runtime_env()
    return os.getenv("DATABASE_PATH", os.path.join(BASE_DIR, "market.db"))


def get_db_connection():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def table_columns(cursor, table_name):
    return {row[1] for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()}


def ensure_column(cursor, table_name, column_name, column_type):
    if column_name not in table_columns(cursor, table_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def ensure_password_hashes(cursor):
    rows = cursor.execute("SELECT id, password FROM users").fetchall()
    for user_id, password in rows:
        if not password:
            continue

        if password.startswith("pbkdf2:") or password.startswith("scrypt:"):
            continue

        cursor.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (generate_password_hash(password), user_id),
        )


def sync_admin_user(cursor):
    load_runtime_env()
    admin_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    admin_password = os.getenv("ADMIN_PASSWORD") or ""
    admin_username = (os.getenv("ADMIN_USERNAME") or "admin").strip() or "admin"
    admin_full_name = (os.getenv("ADMIN_FULL_NAME") or "System Administrator").strip() or "System Administrator"

    if not admin_email or not admin_password:
        return

    hashed_password = generate_password_hash(admin_password)
    existing_admin = cursor.execute(
        "SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1"
    ).fetchone()

    if existing_admin:
        cursor.execute(
            """
            UPDATE users
            SET username = ?, email = ?, password = ?, role = 'admin', full_name = ?, is_verified = 1
            WHERE id = ?
            """,
            (admin_username, admin_email, hashed_password, admin_full_name, existing_admin["id"]),
        )
        return

    cursor.execute(
        """
        INSERT INTO users (username, email, password, role, full_name, is_verified)
        VALUES (?, ?, ?, 'admin', ?, 1)
        """,
        (admin_username, admin_email, hashed_password, admin_full_name),
    )


def init_db():
    load_runtime_env()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA foreign_keys = ON")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            full_name TEXT,
            contact TEXT,
            city TEXT,
            state TEXT,
            district TEXT,
            pincode TEXT,
            latitude REAL,
            longitude REAL,
            is_verified INTEGER DEFAULT 0
        )
        """
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email) WHERE email IS NOT NULL"
    )

    cursor.execute(
        """
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
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            crop_id INTEGER NOT NULL,
            quantity REAL NOT NULL,
            total_price REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            estimated_delivery TEXT,
            current_location TEXT,
            FOREIGN KEY (customer_id) REFERENCES users (id),
            FOREIGN KEY (crop_id) REFERENCES crops (id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS order_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            update_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            location TEXT,
            FOREIGN KEY (order_id) REFERENCES orders (id)
        )
        """
    )

    cursor.execute(
        """
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
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS otp_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            scope TEXT NOT NULL,
            requested_at INTEGER NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_otp_requests_email_scope_time ON otp_requests(email, scope, requested_at)"
    )

    for column_name, column_type in [
        ("email", "TEXT"),
        ("city", "TEXT"),
        ("state", "TEXT"),
        ("district", "TEXT"),
        ("pincode", "TEXT"),
        ("latitude", "REAL"),
        ("longitude", "REAL"),
        ("is_verified", "INTEGER DEFAULT 0"),
    ]:
        ensure_column(cursor, "users", column_name, column_type)

    for column_name, column_type in [
        ("image_url", "TEXT"),
        ("category", "TEXT"),
        ("harvest_date", "TEXT"),
        ("state", "TEXT"),
        ("district", "TEXT"),
        ("village", "TEXT"),
        ("pincode", "TEXT"),
        ("quality", "TEXT"),
        ("quality_proof", "TEXT"),
    ]:
        ensure_column(cursor, "crops", column_name, column_type)

    for column_name, column_type in [
        ("estimated_delivery", "TEXT"),
        ("current_location", "TEXT"),
    ]:
        ensure_column(cursor, "orders", column_name, column_type)

    ensure_password_hashes(cursor)
    sync_admin_user(cursor)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")

import sqlite3, os

DB_FILE = os.path.join(os.path.dirname(__file__), "parking.db")

def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS parking_spots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        spot_number TEXT UNIQUE,
        vehicle_type TEXT,
        is_occupied INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mobile TEXT,
        sticker_id TEXT,
        vehicle_no TEXT,
        vehicle_type TEXT,
        monthly_rate REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_no TEXT,
        vehicle_type TEXT,
        spot_number TEXT,
        entry_time TEXT,
        exit_time TEXT,
        charges REAL DEFAULT 0,
        payment_mode TEXT,
        payment_time TEXT,
        receipt_no TEXT
    );
    CREATE TABLE IF NOT EXISTS login_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        email TEXT
    );
    """)
    conn.commit()

    # --- ✅ Auto-migrate: add phone column if missing ---
    cur.execute("PRAGMA table_info(login_users)")
    cols = [row[1] for row in cur.fetchall()]
    if "phone" not in cols:
        cur.execute("ALTER TABLE login_users ADD COLUMN phone TEXT;")  # no UNIQUE here
        conn.commit()

    # --- Seed default admin user if table empty ---
    cur.execute("SELECT COUNT(*) as cnt FROM login_users")
    if cur.fetchone()["cnt"] == 0:
        cur.execute(
            "INSERT INTO login_users (username, password, email, phone) VALUES (?,?,?,?)",
            ("admin", "admin123", "admin@example.com", "9999999999")
        )
        conn.commit()

    conn.close()

def seed_spots(spots_config):
    conn = get_conn()
    cur = conn.cursor()
    for vtype, count in spots_config.items():
        for i in range(1, count+1):
            spot_no = f"{vtype}-{i:02d}"
            try:
                cur.execute(
                    "INSERT INTO parking_spots (spot_number, vehicle_type) VALUES (?, ?)",
                    (spot_no, vtype)
                )
            except sqlite3.IntegrityError:
                pass
    conn.commit()
    conn.close()

def reset_occupancy():
    """Reset all parking spots to free (used on app startup for demo/test)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE parking_spots SET is_occupied=0")
    conn.commit()
    conn.close()

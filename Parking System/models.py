from db import get_conn
from datetime import datetime
import math, uuid

# -----------------------------------
# Parking Rate Configuration
# -----------------------------------
RATES = {
    '2W': {'hourly': 10, 'daily': 100, 'monthly': 1500},
    '4W': {'hourly': 20, 'daily': 400, 'monthly': 4000},
    'Truck': {'hourly': 50, 'daily': 800, 'monthly': 0},
    'PD': {'hourly': 5, 'daily': 50, 'monthly': 0}
}

# User Registration (Fixed Function)
# -----------------------------------
def register_user(mobile, sticker_id, vehicle_no, vehicle_type, monthly_rate=0):
    """
    Registers a vehicle as a monthly user.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (mobile, sticker_id, vehicle_no, vehicle_type, monthly_rate)
        VALUES (?, ?, ?, ?, ?)
    """, (mobile, sticker_id, vehicle_no.upper(), vehicle_type, monthly_rate))
    conn.commit()
    conn.close()
    return True

# Parking Availability
def availability_summary():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT vehicle_type,
               SUM(CASE WHEN is_occupied=0 THEN 1 ELSE 0 END) as free,
               SUM(CASE WHEN is_occupied=1 THEN 1 ELSE 0 END) as occupied,
               COUNT(*) as total
        FROM parking_spots
        GROUP BY vehicle_type
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

# Reports - Daily & Monthly

def report_collection_by_day():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT date(payment_time) as day, SUM(charges) as total
        FROM transactions
        WHERE payment_time IS NOT NULL AND charges > 0
        GROUP BY day ORDER BY day DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

def report_collection_by_month():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT strftime('%Y-%m', payment_time) as month, SUM(charges) as total
        FROM transactions
        WHERE payment_time IS NOT NULL AND charges > 0
        GROUP BY month ORDER BY month DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

def detailed_report_by_day():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT date(payment_time) as day, vehicle_no, charges, payment_time
        FROM transactions
        WHERE payment_time IS NOT NULL AND charges > 0
        ORDER BY day DESC, payment_time DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

def detailed_report_by_month():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT strftime('%Y-%m', payment_time) as month, vehicle_no, charges, payment_time
        FROM transactions
        WHERE payment_time IS NOT NULL AND charges > 0
        ORDER BY month DESC, payment_time DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

# Helper Functions
# -----------------------------------
def find_free_spot_for_type(vtype):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT spot_number
        FROM parking_spots
        WHERE vehicle_type=? AND is_occupied=0
        ORDER BY spot_number ASC LIMIT 1
    """, (vtype,))
    row = cur.fetchone()
    conn.close()
    return row["spot_number"] if row else None

def mark_spot_occupied(spot, occupied=1):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE parking_spots SET is_occupied=? WHERE spot_number=?",
                (1 if occupied else 0, spot))
    conn.commit()
    conn.close()

def get_open_transaction(vehicle_no):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT *
        FROM transactions
        WHERE vehicle_no=? AND exit_time IS NULL
        ORDER BY id DESC LIMIT 1
    """, (vehicle_no,))
    row = cur.fetchone()
    conn.close()
    return row

# Vehicle Entry Logic
# -----------------------------------
def vehicle_entry(vehicle_no, vtype):
    vehicle_no = vehicle_no.upper().strip()

    open_tx = get_open_transaction(vehicle_no)
    if open_tx:
        return None, f"Vehicle {vehicle_no} already inside (spot {open_tx['spot_number']})."

    spot = find_free_spot_for_type(vtype)
    if not spot:
        return None, f"No free {vtype} spots available."

    entry_time = datetime.utcnow().isoformat(timespec='seconds')
    receipt_no = str(uuid.uuid4())[:8]

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO transactions (vehicle_no, vehicle_type, spot_number, entry_time, receipt_no)
        VALUES (?, ?, ?, ?, ?)
    """, (vehicle_no, vtype, spot, entry_time, receipt_no))
    conn.commit()
    conn.close()

    mark_spot_occupied(spot, 1)

    info = {
        "vehicle_no": vehicle_no,
        "spot": spot,
        "entry_time": entry_time,
        "receipt_no": receipt_no
    }
    return spot, info

# Calculate Charges
# -----------------------------------
def _compute_charges(entry, exit_t, vtype, monthly=False):
    entry_t = datetime.fromisoformat(entry)
    exit_t = datetime.fromisoformat(exit_t)
    duration = exit_t - entry_t
    hours = math.ceil(duration.total_seconds() / 3600)

    if monthly:
        return 0.0, hours, duration

    rate = RATES[vtype]
    if hours >= 24:
        days = math.ceil(hours / 24)
        return days * rate['daily'], hours, duration
    return hours * rate['hourly'], hours, duration

# Vehicle Exit Logic
# -----------------------------------
def process_exit(vehicle_no, pay_mode):
    vehicle_no = vehicle_no.upper().strip()
    tx = get_open_transaction(vehicle_no)

    if not tx:
        return None, f"No active entry for {vehicle_no}"

    conn = get_conn()
    cur = conn.cursor()

    # Check if user is a monthly subscriber
    cur.execute("SELECT monthly_rate FROM users WHERE vehicle_no=? LIMIT 1", (vehicle_no,))
    user = cur.fetchone()
    monthly = bool(user and user["monthly_rate"] > 0)

    exit_time = datetime.utcnow().isoformat(timespec='seconds')
    charge, hours, duration = _compute_charges(tx["entry_time"], exit_time, tx["vehicle_type"], monthly)
    payment_time = datetime.utcnow().isoformat(timespec='seconds')

    cur.execute("""
        UPDATE transactions
        SET exit_time=?, charges=?, payment_mode=?, payment_time=?
        WHERE id=?
    """, (exit_time, charge, pay_mode, payment_time, tx["id"]))
    conn.commit()
    conn.close()

    mark_spot_occupied(tx["spot_number"], 0)

    receipt = {
        "vehicle_no": vehicle_no,
        "spot": tx["spot_number"],
        "entry_time": tx["entry_time"],
        "exit_time": exit_time,
        "charges": charge,
        "hours": hours,
        "payment_mode": pay_mode
    }
    return receipt, None

import os
import hashlib
import urllib.parse
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

# Automatically load local .env if present
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_file):
    try:
        with open(_env_file, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k = _k.strip()
                    _v = _v.strip().strip("'\"")
                    if _k not in os.environ:
                        os.environ[_k] = _v
    except Exception:
        pass

DATABASE_URL = (os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL") or "").strip()
DB_FILE = os.environ.get("DB_FILE", "meesho_studio.db")

IS_POSTGRES = bool(
    DATABASE_URL
    and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://"))
)

if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras

    # Normalize url scheme if necessary
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    # Handle unencoded special characters (e.g. '@' in database password)
    if "://" in DATABASE_URL:
        scheme, rest = DATABASE_URL.split("://", 1)
        if "@" in rest and rest.count("@") > 1:
            auth_part, host_part = rest.rsplit("@", 1)
            if ":" in auth_part:
                user_part, pwd_part = auth_part.split(":", 1)
                encoded_pwd = urllib.parse.quote(pwd_part, safe="")
                DATABASE_URL = f"{scheme}://{user_part}:{encoded_pwd}@{host_part}"

    # Clean query parameters unsupported by psycopg2 / libpq (e.g. pgbouncer=true)
    try:
        parsed_url = urllib.parse.urlparse(DATABASE_URL)
        if parsed_url.query:
            allowed_params = {
                "sslmode", "sslcert", "sslkey", "sslrootcert",
                "connect_timeout", "application_name", "options",
                "target_session_attrs", "keepalives", "keepalives_idle"
            }
            query_pairs = urllib.parse.parse_qsl(parsed_url.query)
            valid_query = [pair for pair in query_pairs if pair[0].lower() in allowed_params]
            new_query = urllib.parse.urlencode(valid_query)
            DATABASE_URL = urllib.parse.urlunparse(parsed_url._replace(query=new_query))
    except Exception:
        if "pgbouncer=" in DATABASE_URL:
            DATABASE_URL = DATABASE_URL.split("?pgbouncer=")[0].split("&pgbouncer=")[0]
else:
    import sqlite3


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


class DBConnection:
    """Wrapper that abstracts differences between SQLite and PostgreSQL."""

    def __init__(self):
        self.is_pg = IS_POSTGRES
        if self.is_pg:
            self.conn = psycopg2.connect(DATABASE_URL)
            self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            self.conn = sqlite3.connect(DB_FILE)
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()

    def _prepare_sql(self, sql: str) -> str:
        if self.is_pg:
            # Replace sqlite '?' placeholder with postgres '%s'
            # Note: be careful not to replace '?' inside quotes if any, but our queries use standard placeholders
            return sql.replace("?", "%s")
        return sql

    def execute(self, sql: str, params: tuple = None) -> Any:
        sql = self._prepare_sql(sql)
        if params is None:
            return self.cursor.execute(sql)
        return self.cursor.execute(sql, params)

    def fetchone(self) -> Optional[Dict[str, Any]]:
        row = self.cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self) -> List[Dict[str, Any]]:
        rows = self.cursor.fetchall()
        return [dict(r) for r in rows]

    def insert_get_id(self, sql: str, params: tuple = None) -> int:
        if self.is_pg:
            # Append RETURNING id if not present
            clean_sql = sql.strip().rstrip(";")
            if "RETURNING" not in clean_sql.upper():
                clean_sql += " RETURNING id"
            self.execute(clean_sql, params)
            res = self.cursor.fetchone()
            return res["id"] if res else 0
        else:
            self.execute(sql, params)
            return self.cursor.lastrowid

    def commit(self):
        self.conn.commit()

    def close(self):
        self.cursor.close()
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.commit()
        else:
            self.conn.rollback()
        self.close()


def init_db():
    """Initializes tables for either SQLite or PostgreSQL (Supabase)."""
    with DBConnection() as db:
        if db.is_pg:
            # PostgreSQL Schema
            db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                email VARCHAR(255),
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'user',
                wallet_balance DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                created_at VARCHAR(50) NOT NULL
            );
            """)

            db.execute("""
            CREATE TABLE IF NOT EXISTS review_tasks (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                mobile VARCHAR(30) NOT NULL,
                user_id_meesho BIGINT,
                order_id VARCHAR(100),
                sub_order_id VARCHAR(100),
                product_title TEXT,
                service_type VARCHAR(50) NOT NULL,
                cost DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
                rating_stars INTEGER DEFAULT 5,
                comments TEXT,
                rating_id VARCHAR(100),
                error_message TEXT,
                raw_json TEXT NOT NULL,
                created_at VARCHAR(50) NOT NULL,
                completed_at VARCHAR(50)
            );
            """)

            db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                amount DOUBLE PRECISION NOT NULL,
                type VARCHAR(50) NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
                utr_ref VARCHAR(100),
                notes TEXT,
                gateway_order_id VARCHAR(100),
                created_at VARCHAR(50) NOT NULL
            );
            """)

            db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT NOT NULL
            );
            """)

        else:
            # SQLite Schema
            db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                wallet_balance REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL
            );
            """)

            db.execute("""
            CREATE TABLE IF NOT EXISTS review_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mobile TEXT NOT NULL,
                user_id_meesho INTEGER,
                order_id TEXT,
                sub_order_id TEXT,
                product_title TEXT,
                service_type TEXT NOT NULL,
                cost REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'PENDING',
                rating_stars INTEGER DEFAULT 5,
                comments TEXT,
                rating_id TEXT,
                error_message TEXT,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """)

            db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                utr_ref TEXT,
                notes TEXT,
                gateway_order_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """)

            db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """)

        # Migrate existing tables if columns are missing
        if db.is_pg:
            try:
                db.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS gateway_order_id TEXT")
                db.conn.commit()
            except Exception:
                db.conn.rollback()
        else:
            try:
                db.execute("ALTER TABLE transactions ADD COLUMN gateway_order_id TEXT")
            except Exception:
                pass

        # Default Settings (0rs signup bonus, 50rs min topup, 10rs and 7rs default prices)
        default_settings = {
            "price_auto_pilot": "10.0",         # Old accounts with auto-refresh & review
            "price_standard_review": "7.0",     # Fresh accounts with instant review
            "min_topup_amount": "50.0",         # Configurable minimum top-up
            "signup_bonus": "0.0",              # ₹0 on signup as requested
            "telegram_bot_enabled": "true",
            "meesho_proxy": os.environ.get("INDIAN_PROXY", ""),
            "famgateway_api_key": os.environ.get("FAMGATEWAY_API_KEY", ""),
            "upi_id": "meesho.reviews@upi",
            "upi_name": "Meesho Automation Studio",
        }

        for k, v in default_settings.items():
            if db.is_pg:
                db.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO NOTHING",
                    (k, v),
                )
            else:
                db.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (k, v),
                )

        # Sync FamGateway API key from environment if provided
        env_fg_key = (os.environ.get("FAMGATEWAY_API_KEY") or "").strip()
        if env_fg_key:
            if db.is_pg:
                db.execute(
                    "INSERT INTO settings (key, value) VALUES ('famgateway_api_key', ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (env_fg_key,),
                )
            else:
                db.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES ('famgateway_api_key', ?)",
                    (env_fg_key,),
                )

        # Default admin account
        db.execute("SELECT id FROM users WHERE username = 'admin'")
        admin_row = db.fetchone()
        env_admin_pwd = (os.environ.get("ADMIN_PASSWORD") or "").strip()
        initial_admin_pwd = env_admin_pwd or "admin123"
        admin_pwd = hash_password(initial_admin_pwd)
        if not admin_row:
            db.execute(
                "INSERT INTO users (username, email, password_hash, role, wallet_balance, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("admin", "admin@studio.local", admin_pwd, "admin", 1000.0, datetime.now().isoformat()),
            )
        elif env_admin_pwd:
            # Sync existing admin password with ADMIN_PASSWORD env var if explicitly set
            db.execute("UPDATE users SET password_hash = ? WHERE username = 'admin'", (admin_pwd,))


# ------------------------------------------------------------
# Settings Operations
# ------------------------------------------------------------
def get_setting(key: str, default: str = "") -> str:
    with DBConnection() as db:
        db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = db.fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with DBConnection() as db:
        if db.is_pg:
            db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, value),
            )
        else:
            db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )


def get_all_settings() -> Dict[str, str]:
    with DBConnection() as db:
        db.execute("SELECT key, value FROM settings")
        rows = db.fetchall()
        return {r["key"]: r["value"] for r in rows}


# ------------------------------------------------------------
# User Operations
# ------------------------------------------------------------
def create_user(username: str, password: str, email: str = "", role: str = "user") -> Optional[int]:
    pwd_hash = hash_password(password)
    bonus = float(get_setting("signup_bonus", "0.0"))
    now = datetime.now().isoformat()
    try:
        with DBConnection() as db:
            user_id = db.insert_get_id(
                "INSERT INTO users (username, email, password_hash, role, wallet_balance, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (username.strip(), email.strip(), pwd_hash, role, bonus, now),
            )
            if bonus > 0:
                db.execute(
                    "INSERT INTO transactions (user_id, amount, type, status, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, bonus, "BONUS", "COMPLETED", "Welcome sign-up credit", now),
                )
            return user_id
    except Exception:
        return None


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    pwd_hash = hash_password(password)
    with DBConnection() as db:
        db.execute(
            "SELECT id, username, email, role, wallet_balance FROM users WHERE username = ? AND password_hash = ?",
            (username.strip(), pwd_hash),
        )
        return db.fetchone()


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with DBConnection() as db:
        db.execute(
            "SELECT id, username, email, role, wallet_balance, created_at FROM users WHERE id = ?",
            (user_id,),
        )
        return db.fetchone()


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    with DBConnection() as db:
        db.execute(
            "SELECT id, username, email, role, wallet_balance, created_at FROM users WHERE username = ?",
            (username.strip(),),
        )
        return db.fetchone()


def change_password(user_id: int, current_password: str, new_password: str) -> Tuple[bool, str]:
    with DBConnection() as db:
        db.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,))
        row = db.fetchone()
        if not row:
            return False, "User not found."

        if row["password_hash"] != hash_password(current_password):
            return False, "Incorrect current password."

        new_hash = hash_password(new_password)
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
        return True, "Password changed successfully."


def get_all_users() -> List[Dict[str, Any]]:
    with DBConnection() as db:
        db.execute("""
            SELECT u.id, u.username, u.email, u.role, u.wallet_balance, u.created_at,
                   COUNT(t.id) as total_tasks,
                   SUM(CASE WHEN t.status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_tasks
            FROM users u
            LEFT JOIN review_tasks t ON u.id = t.user_id
            GROUP BY u.id, u.username, u.email, u.role, u.wallet_balance, u.created_at
            ORDER BY u.id DESC
        """)
        return db.fetchall()


def update_user_balance(user_id: int, delta: float, tx_type: str, notes: str = "", utr: str = "", gateway_order_id: str = "") -> bool:
    """
    Atomically updates a user's wallet balance.
    If delta is negative (deduction), uses an atomic conditional WHERE clause to guarantee no overdrawing.
    """
    with DBConnection() as db:
        if delta < 0:
            deduct_amount = round(abs(delta), 2)
            db.execute(
                "UPDATE users SET wallet_balance = wallet_balance - ? WHERE id = ? AND wallet_balance >= ?",
                (deduct_amount, user_id, deduct_amount),
            )
            if db.cursor.rowcount == 0:
                return False  # Atomic check failed: Insufficient balance
        else:
            add_amount = round(delta, 2)
            db.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE id = ?", (add_amount, user_id))
            if db.cursor.rowcount == 0:
                return False

        now = datetime.now().isoformat()
        db.execute(
            "INSERT INTO transactions (user_id, amount, type, status, utr_ref, notes, gateway_order_id, created_at) VALUES (?, ?, ?, 'COMPLETED', ?, ?, ?, ?)",
            (user_id, abs(round(delta, 2)), tx_type, utr, notes, gateway_order_id, now),
        )
        return True


# ------------------------------------------------------------
# Task / Review Operations
# ------------------------------------------------------------
def create_task(user_id: int, mobile: str, service_type: str, cost: float, rating_stars: int, comments: str, raw_json: str) -> int:
    now = datetime.now().isoformat()
    with DBConnection() as db:
        task_id = db.insert_get_id("""
            INSERT INTO review_tasks (user_id, mobile, service_type, cost, rating_stars, comments, raw_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
        """, (user_id, mobile, service_type, cost, rating_stars, comments, raw_json, now))
        return task_id


def update_task_status(
    task_id: int,
    status: str,
    order_id: str = None,
    sub_order_id: str = None,
    product_title: str = None,
    rating_id: str = None,
    error: str = None,
):
    now = datetime.now().isoformat() if status in ("COMPLETED", "FAILED") else None
    with DBConnection() as db:
        db.execute("""
            UPDATE review_tasks
            SET status = ?,
                order_id = COALESCE(?, order_id),
                sub_order_id = COALESCE(?, sub_order_id),
                product_title = COALESCE(?, product_title),
                rating_id = COALESCE(?, rating_id),
                error_message = ?,
                completed_at = COALESCE(?, completed_at)
            WHERE id = ?
        """, (status, order_id, sub_order_id, product_title, rating_id, error, now, task_id))


def get_user_tasks(user_id: int) -> List[Dict[str, Any]]:
    with DBConnection() as db:
        db.execute("""
            SELECT id, mobile, order_id, product_title, service_type, cost, status,
                   rating_stars, comments, rating_id, error_message, created_at, completed_at
            FROM review_tasks
            WHERE user_id = ?
            ORDER BY id DESC
        """, (user_id,))
        return db.fetchall()


def get_all_tasks() -> List[Dict[str, Any]]:
    with DBConnection() as db:
        db.execute("""
            SELECT t.id, t.user_id, u.username, t.mobile, t.order_id, t.product_title,
                   t.service_type, t.cost, t.status, t.rating_stars, t.comments,
                   t.rating_id, t.error_message, t.created_at, t.completed_at
            FROM review_tasks t
            JOIN users u ON t.user_id = u.id
            ORDER BY t.id DESC
        """)
        return db.fetchall()


def get_user_stats(user_id: int) -> Dict[str, Any]:
    with DBConnection() as db:
        db.execute("""
            SELECT
                COUNT(id) as total_submitted,
                SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as total_completed,
                SUM(CASE WHEN status = 'PENDING' OR status = 'PROCESSING' THEN 1 ELSE 0 END) as total_pending,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as total_failed
            FROM review_tasks
            WHERE user_id = ?
        """, (user_id,))
        row = db.fetchone()
        return {
            "submitted": row["total_submitted"] or 0,
            "completed": row["total_completed"] or 0,
            "pending": row["total_pending"] or 0,
            "failed": row["total_failed"] or 0,
        }


# ------------------------------------------------------------
# Transaction / Payment Operations
# ------------------------------------------------------------
def is_utr_already_used(utr_ref: str) -> bool:
    """Returns True if this UTR has already been submitted in any PENDING or COMPLETED deposit."""
    clean = (utr_ref or "").strip()
    if not clean or clean.upper() == "FAMGATEWAY":
        return False
    with DBConnection() as db:
        db.execute(
            "SELECT id FROM transactions WHERE UPPER(utr_ref) = UPPER(?) AND status IN ('PENDING', 'COMPLETED')",
            (clean,),
        )
        return db.fetchone() is not None


def create_deposit_request(user_id: int, amount: float, utr_ref: str, gateway_order_id: str = "") -> int:
    """Creates a new deposit request with anti-duplicate fraud prevention."""
    clean_utr = (utr_ref or "").strip()
    clean_amt = round(float(amount), 2)
    if clean_amt <= 0:
        raise ValueError("Invalid deposit amount.")

    if clean_utr and clean_utr.upper() != "FAMGATEWAY":
        if is_utr_already_used(clean_utr):
            raise ValueError("This UPI UTR reference number has already been submitted or processed. Duplicate submissions are not accepted.")

    now = datetime.now().isoformat()
    with DBConnection() as db:
        tx_id = db.insert_get_id("""
            INSERT INTO transactions (user_id, amount, type, status, utr_ref, notes, gateway_order_id, created_at)
            VALUES (?, ?, 'DEPOSIT', 'PENDING', ?, 'Payment request', ?, ?)
        """, (user_id, clean_amt, clean_utr, gateway_order_id, now))
        return tx_id


def get_user_transactions(user_id: int) -> List[Dict[str, Any]]:
    with DBConnection() as db:
        db.execute("""
            SELECT id, amount, type, status, utr_ref, notes, gateway_order_id, created_at
            FROM transactions
            WHERE user_id = ?
            ORDER BY id DESC
        """, (user_id,))
        return db.fetchall()


def get_transaction_by_gateway_order(gateway_order_id: str) -> Optional[Dict[str, Any]]:
    with DBConnection() as db:
        db.execute("""
            SELECT id, user_id, amount, type, status, utr_ref, notes, gateway_order_id, created_at
            FROM transactions
            WHERE gateway_order_id = ?
        """, (gateway_order_id,))
        return db.fetchone()


def get_pending_deposits() -> List[Dict[str, Any]]:
    with DBConnection() as db:
        db.execute("""
            SELECT t.id, t.user_id, u.username, t.amount, t.utr_ref, t.gateway_order_id, t.created_at
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE t.type = 'DEPOSIT' AND t.status = 'PENDING'
            ORDER BY t.id ASC
        """)
        return db.fetchall()


def approve_deposit(tx_id: int) -> bool:
    """Atomically approves a pending deposit, preventing double-crediting."""
    with DBConnection() as db:
        db.execute("SELECT user_id, amount, status FROM transactions WHERE id = ?", (tx_id,))
        row = db.fetchone()
        if not row or row["status"] != "PENDING":
            return False

        user_id = row["user_id"]
        amount = round(float(row["amount"]), 2)

        # Atomic conditional status update to prevent race conditions
        db.execute("UPDATE transactions SET status = 'COMPLETED', notes = 'Approved by Admin' WHERE id = ? AND status = 'PENDING'", (tx_id,))
        if db.cursor.rowcount == 0:
            return False

        db.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE id = ?", (amount, user_id))
        return True


def reject_deposit(tx_id: int) -> bool:
    with DBConnection() as db:
        db.execute("UPDATE transactions SET status = 'REJECTED', notes = 'Rejected by Admin' WHERE id = ? AND status = 'PENDING'", (tx_id,))
        return db.cursor.rowcount > 0


def complete_gateway_deposit(gateway_order_id: str, verified_amount: Optional[float] = None) -> bool:
    """
    Atomically auto-credits wallet when FamGateway confirms an order.
    Guarantees idempotency and prevents double-crediting.
    """
    with DBConnection() as db:
        db.execute("SELECT id, user_id, amount, status FROM transactions WHERE gateway_order_id = ?", (gateway_order_id,))
        row = db.fetchone()
        if not row or row["status"] != "PENDING":
            return False

        tx_id = row["id"]
        user_id = row["user_id"]
        amount = round(float(verified_amount), 2) if verified_amount is not None else round(float(row["amount"]), 2)

        # Atomic conditional update
        db.execute(
            "UPDATE transactions SET status = 'COMPLETED', amount = ?, notes = 'Verified by FamGateway' WHERE id = ? AND status = 'PENDING'",
            (amount, tx_id),
        )
        if db.cursor.rowcount == 0:
            return False  # Already completed concurrently

        db.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE id = ?", (amount, user_id))
        return True


# Run initialization on import
init_db()

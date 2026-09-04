"""
db.py - SQLite Durable Persistence Layer for Razorpay AI Revenue Recovery Agent.
Supports WAL journal mode, atomic transaction tracking, idempotency, escalations,
checkout sessions, and B2B invoices.
"""

import os
import json
import sqlite3
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "recovery_state.db")


def get_db_path() -> str:
    return os.getenv("RECOVERY_DB_PATH", DEFAULT_DB_PATH)


def get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL mode for robust concurrency during webhook bursts
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


@contextmanager
def get_db(db_path: Optional[str] = None):
    """Context manager for safe, auto-committing database connections."""
    conn = get_conn(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """Initializes all required schema tables if they do not exist."""
    with get_db(db_path) as conn:
        # 1. Transaction & Cooldown state (Priority 1)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transaction_state (
                tracking_key TEXT PRIMARY KEY,
                failure_count INTEGER NOT NULL DEFAULT 0,
                last_action TEXT,
                last_action_ts REAL,
                action_history_json TEXT NOT NULL DEFAULT '[]'
            )
        """)

        # 2. Webhook Event Idempotency (Priority 1)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                processed_at REAL NOT NULL
            )
        """)

        # 3. Human Escalation Queue (Priority 2)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS escalations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT,
                order_id TEXT,
                amount_inr REAL,
                reason TEXT,
                rule_triggered TEXT,
                created_at REAL,
                status TEXT DEFAULT 'open',
                resolved_at REAL,
                resolver_notes TEXT
            )
        """)

        # 4. Checkout Sessions & Abandonment (Priority 3)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkout_sessions (
                session_id TEXT PRIMARY KEY,
                order_id TEXT,
                amount_inr REAL,
                customer_email TEXT,
                customer_contact TEXT,
                cart_step TEXT,
                method_attempted TEXT,
                created_at REAL,
                completed_at REAL,
                nudge_count INTEGER DEFAULT 0,
                last_nudge_ts REAL
            )
        """)

        # 5. B2B Invoices & Receivables Chaser (Priority 4)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                invoice_id TEXT PRIMARY KEY,
                customer_id TEXT,
                customer_tier TEXT,
                amount_inr REAL,
                due_date REAL,
                status TEXT DEFAULT 'overdue',
                stage TEXT DEFAULT 'none',
                last_contact_ts REAL,
                promised_pay_date REAL,
                broken_promise_count INTEGER DEFAULT 0
            )
        """)


def is_event_processed(event_id: str, db_path: Optional[str] = None) -> bool:
    """Checks if a webhook event ID has already been recorded."""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return row is not None


def record_processed_event(event_id: str, ts: Optional[float] = None, db_path: Optional[str] = None) -> None:
    """Records an incoming webhook event ID for idempotency."""
    import time
    timestamp = ts if ts is not None else time.time()
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO processed_events (event_id, processed_at) VALUES (?, ?)",
            (event_id, timestamp),
        )


def reset_db(db_path: Optional[str] = None) -> None:
    """Clears all records from tables (primarily for test isolation)."""
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM transaction_state")
        conn.execute("DELETE FROM processed_events")
        conn.execute("DELETE FROM escalations")
        conn.execute("DELETE FROM checkout_sessions")
        conn.execute("DELETE FROM invoices")

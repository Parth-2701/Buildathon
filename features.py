"""
features.py - Feature extraction and durable transaction history tracking.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent
"""

import time
import json
from typing import Dict, Any, Optional
from constants import COOLDOWN_WINDOW_SECONDS
from db import get_db, init_db


class TransactionTracker:
    """
    Durable SQLite-backed tracker for transaction attempts, cooldowns, and prior failures.
    Persists across process restarts and webhook bursts using WAL mode.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        init_db(self.db_path)

    def get_record(self, key: str) -> Dict[str, Any]:
        with get_db(self.db_path) as conn:
            row = conn.execute(
                "SELECT failure_count, last_action, last_action_ts, action_history_json "
                "FROM transaction_state WHERE tracking_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return {
                    "failure_count": 0,
                    "action_history": [],
                    "last_action_timestamp": None,
                }
            return {
                "failure_count": row["failure_count"],
                "action_history": json.loads(row["action_history_json"] or "[]"),
                "last_action_timestamp": row["last_action_ts"],
            }

    def record_failure(self, key: str) -> int:
        with get_db(self.db_path) as conn:
            conn.execute("""
                INSERT INTO transaction_state (tracking_key, failure_count, action_history_json)
                VALUES (?, 1, '[]')
                ON CONFLICT(tracking_key) DO UPDATE SET failure_count = failure_count + 1
            """, (key,))
            row = conn.execute(
                "SELECT failure_count FROM transaction_state WHERE tracking_key = ?",
                (key,),
            ).fetchone()
            return row["failure_count"] if row else 1

    def record_action(self, key: str, action: str, timestamp: Optional[float] = None) -> None:
        ts = timestamp if timestamp is not None else time.time()
        with get_db(self.db_path) as conn:
            row = conn.execute(
                "SELECT action_history_json FROM transaction_state WHERE tracking_key = ?",
                (key,),
            ).fetchone()
            if row:
                history = json.loads(row["action_history_json"] or "[]")
                history.append({"action": action, "timestamp": ts})
                conn.execute("""
                    UPDATE transaction_state
                    SET last_action = ?, last_action_ts = ?, action_history_json = ?
                    WHERE tracking_key = ?
                """, (action, ts, json.dumps(history), key))
            else:
                history = [{"action": action, "timestamp": ts}]
                conn.execute("""
                    INSERT INTO transaction_state (tracking_key, failure_count, last_action, last_action_ts, action_history_json)
                    VALUES (?, 0, ?, ?, ?)
                """, (key, action, ts, json.dumps(history)))

    def get_prior_failures(self, key: str) -> int:
        return self.get_record(key)["failure_count"]

    def get_seconds_since_last_action(self, key: str, current_time: Optional[float] = None) -> Optional[float]:
        ts = current_time if current_time is not None else time.time()
        last_ts = self.get_record(key)["last_action_timestamp"]
        if last_ts is None:
            return None
        return max(0.0, ts - last_ts)

    def is_in_cooldown(self, key: str, cooldown_seconds: int = COOLDOWN_WINDOW_SECONDS, current_time: Optional[float] = None) -> bool:
        elapsed = self.get_seconds_since_last_action(key, current_time)
        if elapsed is None:
            return False
        return elapsed < cooldown_seconds

    def reset(self) -> None:
        """Clear all transaction states (useful for tests)."""
        with get_db(self.db_path) as conn:
            conn.execute("DELETE FROM transaction_state")


# Global tracker instance backed by recovery_state.db
global_tracker = TransactionTracker()


def normalize_error_code(raw_error_reason: Optional[str], raw_error_code: Optional[str]) -> str:
    """
    Normalizes error codes and reasons from Razorpay webhook payloads
    into standard keys defined in constants.py.
    """
    candidate = raw_error_reason or raw_error_code or "unknown"
    normalized = candidate.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized


def build_features(
    payment_entity: Dict[str, Any],
    tracker: Optional[TransactionTracker] = None,
    current_time: Optional[float] = None,
    custom_tracking_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extracts a structured feature dictionary from a Razorpay payment entity dict.
    """
    if tracker is None:
        tracker = global_tracker

    ts = current_time if current_time is not None else time.time()

    txn_id = payment_entity.get("id", "")
    order_id = payment_entity.get("order_id")
    # Group by custom_tracking_key (e.g. subscription_id) / order_id / txn_id
    tracking_key = custom_tracking_key or order_id or txn_id

    # Retrieve prior failures BEFORE recording this new failure
    prior_failures = tracker.get_prior_failures(tracking_key)
    seconds_since_last_action = tracker.get_seconds_since_last_action(tracking_key, ts)
    is_cooling_down = tracker.is_in_cooldown(tracking_key, COOLDOWN_WINDOW_SECONDS, ts)

    raw_error_code = payment_entity.get("error_code")
    raw_error_reason = payment_entity.get("error_reason")
    raw_error_desc = payment_entity.get("error_description")
    normalized_code = normalize_error_code(raw_error_reason, raw_error_code)

    amount = payment_entity.get("amount", 0)
    currency = payment_entity.get("currency", "INR")
    method = payment_entity.get("method")
    
    customer_email = payment_entity.get("email")
    customer_contact = payment_entity.get("contact")

    card_info = payment_entity.get("card") or {}
    card_network = card_info.get("network")
    card_type = card_info.get("type")
    vpa = payment_entity.get("vpa")

    return {
        "transaction_id": txn_id,
        "order_id": order_id,
        "tracking_key": tracking_key,
        "amount": amount,                      # in paise
        "amount_inr": amount / 100.0 if amount else 0.0,
        "currency": currency,
        "method": method,
        "error_code": normalized_code,
        "raw_error_code": raw_error_code,
        "raw_error_reason": raw_error_reason,
        "raw_error_description": raw_error_desc,
        "prior_failures": prior_failures,
        "seconds_since_last_action": seconds_since_last_action,
        "is_in_cooldown": is_cooling_down,
        "customer_email": customer_email,
        "customer_contact": customer_contact,
        "card_network": card_network,
        "card_type": card_type,
        "vpa": vpa,
        "timestamp": ts,
    }

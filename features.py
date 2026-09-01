"""
features.py - Feature extraction and transaction history tracking.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent
"""

import time
from typing import Dict, Any, Optional
from constants import COOLDOWN_WINDOW_SECONDS


class TransactionTracker:
    """
    Thread-safe / in-memory tracker for transaction attempts, cooldowns, and prior failures.
    Tracks state by transaction or order ID.
    """

    def __init__(self):
        # key -> {"failure_count": int, "action_history": list, "last_action_timestamp": float}
        self._history: Dict[str, Dict[str, Any]] = {}

    def get_record(self, key: str) -> Dict[str, Any]:
        if key not in self._history:
            self._history[key] = {
                "failure_count": 0,
                "action_history": [],
                "last_action_timestamp": None,
            }
        return self._history[key]

    def record_failure(self, key: str) -> int:
        record = self.get_record(key)
        record["failure_count"] += 1
        return record["failure_count"]

    def record_action(self, key: str, action: str, timestamp: Optional[float] = None) -> None:
        ts = timestamp if timestamp is not None else time.time()
        record = self.get_record(key)
        record["action_history"].append({"action": action, "timestamp": ts})
        record["last_action_timestamp"] = ts

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
        """Clear history (useful for tests)."""
        self._history.clear()


# Global in-memory tracker instance
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
) -> Dict[str, Any]:
    """
    Extracts a structured feature dictionary from a Razorpay payment entity dict.
    
    Args:
        payment_entity: Razorpay payment entity dict (from webhook payload)
        tracker: Optional TransactionTracker instance (defaults to global_tracker)
        current_time: Optional unix timestamp for deterministic testing
        
    Returns:
        Structured dictionary of features ready for policy evaluation.
    """
    if tracker is None:
        tracker = global_tracker

    ts = current_time if current_time is not None else time.time()

    txn_id = payment_entity.get("id", "")
    order_id = payment_entity.get("order_id")
    # Group by order_id if present (since retries may create new payment IDs for same order)
    tracking_key = order_id if order_id else txn_id

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

    # Card / VPA metadata if present
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

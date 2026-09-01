"""
audit.py - Structured audit logging for compliance, stopping rule verification, and metrics.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent
"""

import csv
import os
import time
from typing import Dict, Any, Optional

AUDIT_LOG_FILE = os.path.join(os.path.dirname(__file__), "audit_log.csv")

FIELDNAMES = [
    "timestamp",
    "iso_time",
    "transaction_id",
    "order_id",
    "amount_inr",
    "error_code",
    "prior_failures",
    "action",
    "rule_triggered",
    "recovery_probability",
    "payment_link_id",
    "payment_link_url",
    "explanation",
]


def init_audit_log(file_path: str = AUDIT_LOG_FILE) -> None:
    """Initializes audit log CSV with headers if it does not already exist."""
    if not os.path.exists(file_path):
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()


def log_decision(
    features: Dict[str, Any],
    decision_action: str,
    rule_triggered: str,
    recovery_probability: float,
    explanation: str,
    payment_link_id: Optional[str] = None,
    payment_link_url: Optional[str] = None,
    file_path: str = AUDIT_LOG_FILE,
) -> Dict[str, Any]:
    """
    Logs an agent policy decision to the audit log CSV.
    
    Returns:
        The written audit record dictionary.
    """
    init_audit_log(file_path)

    ts = features.get("timestamp", time.time())
    iso_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

    record = {
        "timestamp": f"{ts:.3f}",
        "iso_time": iso_time,
        "transaction_id": features.get("transaction_id", ""),
        "order_id": features.get("order_id", ""),
        "amount_inr": f"{features.get('amount_inr', 0.0):.2f}",
        "error_code": features.get("error_code", ""),
        "prior_failures": features.get("prior_failures", 0),
        "action": decision_action,
        "rule_triggered": rule_triggered,
        "recovery_probability": f"{recovery_probability:.2f}",
        "payment_link_id": payment_link_id or "",
        "payment_link_url": payment_link_url or "",
        "explanation": explanation,
    }

    with open(file_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writerow(record)

    return record

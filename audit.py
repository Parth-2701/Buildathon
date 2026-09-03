"""
audit.py - Tamper-evident, hash-chained audit logging for compliance and verification.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent
"""

import csv
import os
import time
import json
import hashlib
from typing import Dict, Any, Tuple, Optional

AUDIT_LOG_FILE = os.path.join(os.path.dirname(__file__), "audit_log.csv")

FIELDNAMES = [
    "timestamp",
    "iso_time",
    "transaction_id",
    "order_id",
    "recovery_type",       # "one_off_payment" or "subscription_mandate"
    "amount_inr",
    "error_code",
    "prior_failures",
    "action",
    "rule_triggered",
    "recovery_probability",
    "payment_link_id",
    "payment_link_url",
    "diagnosis_text",      # LLM root-cause diagnosis
    "customer_message",    # Personalized customer outreach copy
    "prev_hash",           # Cryptographic hash chain link
    "entry_hash",          # SHA-256 tamper-evident row signature
]

GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"


def init_audit_log(file_path: str = AUDIT_LOG_FILE) -> None:
    """Initializes audit log CSV with headers if it does not already exist."""
    if not os.path.exists(file_path):
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()


def _get_last_entry_hash(file_path: str = AUDIT_LOG_FILE) -> str:
    """Reads the entry_hash of the last row in the CSV to maintain the hash chain."""
    if not os.path.exists(file_path):
        return GENESIS_HASH
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            if not reader:
                return GENESIS_HASH
            return reader[-1].get("entry_hash") or GENESIS_HASH
    except Exception:
        return GENESIS_HASH


def compute_entry_hash(prev_hash: str, record_data: Dict[str, Any]) -> str:
    """Computes SHA-256 cryptographic hash over previous hash + sorted string-normalized fields."""
    normalized_data = {k: str(record_data.get(k, "")) for k in record_data}
    serialized = prev_hash + "|" + json.dumps(normalized_data, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def log_decision(
    features: Dict[str, Any],
    decision_action: str,
    rule_triggered: str,
    recovery_probability: float,
    explanation: Optional[str] = None,
    diagnosis_text: Optional[str] = None,
    customer_message: Optional[str] = None,
    payment_link_id: Optional[str] = None,
    payment_link_url: Optional[str] = None,
    recovery_type: str = "one_off_payment",
    file_path: str = AUDIT_LOG_FILE,
) -> Dict[str, Any]:
    """
    Logs an agent policy decision to the hash-chained audit log CSV.
    
    Returns:
        The written audit record dictionary.
    """
    init_audit_log(file_path)
    prev_hash = _get_last_entry_hash(file_path)

    ts = features.get("timestamp", time.time())
    iso_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

    base_data = {
        "timestamp": f"{ts:.3f}",
        "iso_time": iso_time,
        "transaction_id": str(features.get("transaction_id", "")),
        "order_id": str(features.get("order_id", "")),
        "recovery_type": str(recovery_type),
        "amount_inr": f"{float(features.get('amount_inr', 0.0)):.2f}",
        "error_code": str(features.get("error_code", "")),
        "prior_failures": str(features.get("prior_failures", 0)),
        "action": str(decision_action),
        "rule_triggered": str(rule_triggered),
        "recovery_probability": f"{float(recovery_probability):.2f}",
        "payment_link_id": str(payment_link_id or ""),
        "payment_link_url": str(payment_link_url or ""),
        "diagnosis_text": str(diagnosis_text or explanation or ""),
        "customer_message": str(customer_message or ""),
    }

    entry_hash = compute_entry_hash(prev_hash, base_data)

    full_record = {
        **base_data,
        "prev_hash": prev_hash,
        "entry_hash": entry_hash,
    }

    with open(file_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writerow(full_record)

    return full_record


def verify_audit_log_integrity(file_path: str = AUDIT_LOG_FILE) -> Tuple[bool, int, Optional[str]]:
    """
    Validates the entire audit log hash chain to detect any tampering or edits.
    
    Returns:
        (is_valid, total_verified_rows, error_message)
    """
    if not os.path.exists(file_path):
        return True, 0, None

    with open(file_path, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        if not reader:
            return True, 0, None

        prev_hash = GENESIS_HASH
        for i, row in enumerate(reader):
            if row.get("prev_hash") != prev_hash:
                return False, i, f"Hash chain broken at row {i+1}: expected prev_hash {prev_hash}, got {row.get('prev_hash')}"
            
            base_data = {k: str(row.get(k, "")) for k in FIELDNAMES if k not in ("prev_hash", "entry_hash")}
            expected_hash = compute_entry_hash(prev_hash, base_data)
            if row.get("entry_hash") != expected_hash:
                return False, i, f"Tampering detected at row {i+1}: expected entry_hash {expected_hash}, got {row.get('entry_hash')}"

            prev_hash = row.get("entry_hash")

    return True, len(reader), None

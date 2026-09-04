"""
escalation.py - Human Escalation Queue & Triage Management.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent

Manages actionable operational handoffs when automated retries are prohibited
by compliance, fraud risk, or high-value exposure thresholds.
"""

import os
import time
import json
import logging
import urllib.request
from typing import Dict, Any, List, Optional
from db import get_db
from audit import log_decision

logger = logging.getLogger("recovery_agent.escalation")

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")


def notify_human_channel(features: Dict[str, Any], rule_triggered: str, explanation: str) -> bool:
    """
    Sends an external notification to the configured operator channel (e.g. Slack).
    Fails gracefully if unconfigured or unreachable.
    """
    if not SLACK_WEBHOOK_URL:
        logger.info(
            "SLACK_WEBHOOK_URL not configured. Escalation recorded in SQLite queue for txn=%s",
            features.get("transaction_id"),
        )
        return False

    payload = {
        "text": (
            f"🚨 *Payment Recovery Escalation Required*\n"
            f"• *Transaction ID:* `{features.get('transaction_id')}`\n"
            f"• *Order ID:* `{features.get('order_id')}`\n"
            f"• *Amount:* INR {features.get('amount_inr', 0.0):,.2f}\n"
            f"• *Rule Triggered:* `{rule_triggered}`\n"
            f"• *Reason:* {explanation}\n"
            f"• *Customer Contact:* {features.get('customer_email') or features.get('customer_contact') or 'N/A'}"
        )
    }

    try:
        req = urllib.request.Request(
            SLACK_WEBHOOK_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning("Failed to dispatch Slack escalation alert (%s). Retained in database.", e)
        return False


def raise_escalation(
    features: Dict[str, Any],
    rule_triggered: str,
    explanation: str,
    diagnosis_text: Optional[str] = None,
) -> int:
    """
    Persists an open human escalation item into the database and dispatches notifications.
    
    Returns:
        The generated escalation ID.
    """
    txn_id = features.get("transaction_id", "")
    order_id = features.get("order_id", "")
    amount_inr = float(features.get("amount_inr", 0.0))
    reason = diagnosis_text or explanation or f"Escalated via {rule_triggered}"
    now = time.time()

    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO escalations (
                transaction_id, order_id, amount_inr, reason, rule_triggered, created_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, 'open')
        """, (txn_id, order_id, amount_inr, reason, rule_triggered, now))
        escalation_id = cursor.lastrowid

    logger.info(
        "Escalation #%d recorded in triage queue for txn=%s (Rule: %s, Amount: INR %.2f)",
        escalation_id, txn_id, rule_triggered, amount_inr
    )

    # Optional outbound alert
    notify_human_channel(features, rule_triggered, explanation)

    return escalation_id


def get_escalations(status: Optional[str] = "open") -> List[Dict[str, Any]]:
    """
    Lists escalations filtered by status ('open', 'in_progress', 'resolved', or None for all).
    """
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM escalations WHERE status = ? ORDER BY id DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM escalations ORDER BY id DESC").fetchall()

        return [dict(row) for row in rows]


def resolve_escalation(
    escalation_id: int,
    notes: str = "",
    resolver: str = "human_operator",
) -> Optional[Dict[str, Any]]:
    """
    Marks an escalation as resolved and records the operational audit trail.
    """
    now = time.time()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM escalations WHERE id = ?", (escalation_id,)).fetchone()
        if not row:
            return None

        conn.execute("""
            UPDATE escalations
            SET status = 'resolved', resolved_at = ?, resolver_notes = ?
            WHERE id = ?
        """, (now, notes, escalation_id))

        updated_row = dict(conn.execute("SELECT * FROM escalations WHERE id = ?", (escalation_id,)).fetchone())

    # Record tamper-evident resolution in audit trail
    log_decision(
        features={
            "transaction_id": updated_row.get("transaction_id", ""),
            "order_id": updated_row.get("order_id", ""),
            "amount_inr": updated_row.get("amount_inr", 0.0),
            "error_code": "escalation_resolved",
            "prior_failures": 0,
        },
        decision_action="ESCALATION_RESOLVED",
        rule_triggered="MANUAL_OPERATOR_RESOLUTION",
        recovery_probability=1.0,
        explanation=f"Escalation #{escalation_id} resolved by {resolver}. Operator notes: {notes}",
        diagnosis_text=f"Resolution note: {notes}",
        customer_message="",
        recovery_type="human_escalation",
    )

    logger.info("Escalation #%d successfully resolved by %s. Notes: %s", escalation_id, resolver, notes)
    return updated_row

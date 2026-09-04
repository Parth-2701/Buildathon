"""
receivables.py - B2B Receivables Engine & Promise-to-Pay Tracker.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent
"""

import time
import logging
from typing import Dict, Any, List, Optional
from db import get_db
from receivables_policy import (
    decide_receivable_action,
    MIN_CONTACT_GAP_DAYS,
)
from executor import create_recovery_payment_link
from audit import log_decision
from llm_diagnostics import generate_diagnosis_and_copy
from escalation import raise_escalation

logger = logging.getLogger("recovery_agent.receivables")


def create_or_update_invoice(data: Dict[str, Any]) -> Dict[str, Any]:
    """Creates or updates a B2B invoice in the database."""
    invoice_id = data["invoice_id"]
    cust_id = data.get("customer_id", "cust_default")
    tier = data.get("customer_tier", "smb")
    amount_inr = float(data.get("amount_inr", 0.0))
    due_date = float(data.get("due_date", time.time()))
    status = data.get("status", "overdue")
    stage = data.get("stage", "none")

    with get_db() as conn:
        conn.execute("""
            INSERT INTO invoices (
                invoice_id, customer_id, customer_tier, amount_inr, due_date, status, stage
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(invoice_id) DO UPDATE SET
                customer_tier = excluded.customer_tier,
                amount_inr = excluded.amount_inr,
                due_date = excluded.due_date,
                status = excluded.status,
                stage = excluded.stage
        """, (invoice_id, cust_id, tier, amount_inr, due_date, status, stage))

    return get_invoice(invoice_id) or {}


def get_invoice(invoice_id: str) -> Optional[Dict[str, Any]]:
    """Fetches an invoice by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)).fetchone()
        return dict(row) if row else None


def record_promise_to_pay(invoice_id: str, promised_date_ts: float) -> Optional[Dict[str, Any]]:
    """
    Registers a formal customer commitment to pay by a specific date.
    Suspends automated reminder outreach until the promised date arrives.
    """
    with get_db() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)).fetchone()
        if not row:
            return None

        conn.execute("""
            UPDATE invoices
            SET status = 'promised', promised_pay_date = ?
            WHERE invoice_id = ?
        """, (promised_date_ts, invoice_id))

        updated = dict(conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)).fetchone())

    # Log commitment into immutable audit ledger
    log_decision(
        features={
            "transaction_id": invoice_id,
            "order_id": invoice_id,
            "amount_inr": updated.get("amount_inr", 0.0),
            "error_code": "promise_to_pay_recorded",
            "prior_failures": updated.get("broken_promise_count", 0),
        },
        decision_action="PROMISE_RECORDED",
        rule_triggered="RULE_REC_PROMISE_RECORDED",
        recovery_probability=0.75,
        explanation=f"Customer submitted Promise to Pay for {time.strftime('%Y-%m-%d', time.localtime(promised_date_ts))}. Dunning paused.",
        diagnosis_text=f"Promise date registered: {time.strftime('%Y-%m-%d', time.localtime(promised_date_ts))}",
        customer_message="Thank you for confirming your payment plan. Automated reminders have been paused.",
        recovery_type="b2b_receivable",
    )

    logger.info("Promise to Pay recorded for invoice %s (due %s)", invoice_id, time.ctime(promised_date_ts))
    return updated


def mark_invoice_paid(invoice_id: str) -> Optional[Dict[str, Any]]:
    """Marks an invoice as paid and permanently halts dunning."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)).fetchone()
        if not row:
            return None

        conn.execute("UPDATE invoices SET status = 'paid' WHERE invoice_id = ?", (invoice_id,))
        updated = dict(conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)).fetchone())

    log_decision(
        features={
            "transaction_id": invoice_id,
            "order_id": invoice_id,
            "amount_inr": updated.get("amount_inr", 0.0),
            "error_code": "invoice_settled",
            "prior_failures": 0,
        },
        decision_action="INVOICE_PAID",
        rule_triggered="RULE_REC_ALREADY_PAID",
        recovery_probability=1.0,
        explanation="B2B invoice paid in full. Dunning sequence terminated.",
        diagnosis_text="Invoice cleared.",
        customer_message="",
        recovery_type="b2b_receivable",
    )

    logger.info("Invoice %s marked as PAID.", invoice_id)
    return updated


def sweep_overdue_invoices(
    current_time: Optional[float] = None,
    min_contact_gap_seconds: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Evaluates all active invoices against the dunning ladder:
    1. Detects expired/broken promises and re-escalates.
    2. Enforces multi-stage reminders and contact cooldowns.
    3. Escalates severe delinquencies or enterprise accounts to collections specialists.
    """
    now = current_time if current_time is not None else time.time()
    results = []

    # 1. Broken Promise Detection
    with get_db() as conn:
        broken_rows = conn.execute("""
            SELECT * FROM invoices
            WHERE status = 'promised' AND promised_pay_date < ?
        """, (now,)).fetchall()

        for b in broken_rows:
            inv = dict(b)
            new_broken = inv.get("broken_promise_count", 0) + 1
            # Broken promises re-enter to immediately receive FINAL_NOTICE (skipping friendly stages)
            conn.execute("""
                UPDATE invoices
                SET status = 'overdue', stage = 'reminder_2', broken_promise_count = ?
                WHERE invoice_id = ?
            """, (new_broken, inv["invoice_id"]))
            logger.warning(
                "Broken Promise detected for invoice %s (Total broken: %d). Escalated to trigger final_notice.",
                inv["invoice_id"], new_broken
            )

    # 2. Evaluate All Active Invoices
    with get_db() as conn:
        active_invoices = conn.execute("SELECT * FROM invoices WHERE status != 'paid'").fetchall()

    for row in active_invoices:
        inv = dict(row)
        invoice_id = inv["invoice_id"]
        amount_inr = float(inv.get("amount_inr", 0.0))

        decision = decide_receivable_action(
            inv,
            current_time=now,
            min_contact_gap_seconds=min_contact_gap_seconds,
        )

        feat = {
            "transaction_id": invoice_id,
            "order_id": invoice_id,
            "amount": int(amount_inr * 100),
            "amount_inr": amount_inr,
            "error_code": f"receivable_{decision.next_stage}",
            "prior_failures": inv.get("broken_promise_count", 0),
            "timestamp": now,
        }

        llm_out = generate_diagnosis_and_copy(
            features=feat,
            action=decision.action,
            rule=decision.rule_triggered,
            recovery_prob=decision.recovery_probability,
        )

        payment_link_id = None
        payment_link_url = None

        if decision.action in ("REMINDER_1", "REMINDER_2", "FINAL_NOTICE"):
            try:
                link_res = create_recovery_payment_link(feat)
                payment_link_id = link_res.get("id")
                payment_link_url = link_res.get("short_url")
            except Exception as e:
                logger.error("Failed to generate payment link for invoice %s: %s", invoice_id, e)

            with get_db() as conn:
                conn.execute("""
                    UPDATE invoices
                    SET stage = ?, last_contact_ts = ?
                    WHERE invoice_id = ?
                """, (decision.next_stage, now, invoice_id))

        elif decision.action in ("ESCALATE_COLLECTIONS", "ESCALATE_HUMAN"):
            raise_escalation(
                features=feat,
                rule_triggered=decision.rule_triggered,
                explanation=decision.explanation,
                diagnosis_text=llm_out.get("diagnosis_text"),
            )
            with get_db() as conn:
                conn.execute("""
                    UPDATE invoices
                    SET stage = 'collections', status = 'escalated_collections', last_contact_ts = ?
                    WHERE invoice_id = ?
                """, (now, invoice_id))

        # Record tamper-evident audit entry
        log_decision(
            features=feat,
            decision_action=decision.action,
            rule_triggered=decision.rule_triggered,
            recovery_probability=decision.recovery_probability,
            explanation=decision.explanation,
            diagnosis_text=llm_out.get("diagnosis_text"),
            customer_message=llm_out.get("customer_message"),
            payment_link_id=payment_link_id,
            payment_link_url=payment_link_url,
            recovery_type="b2b_receivable",
        )

        results.append({
            "invoice_id": invoice_id,
            "action": decision.action,
            "stage": decision.next_stage,
            "rule": decision.rule_triggered,
            "payment_link": payment_link_url,
            "diagnosis": llm_out.get("diagnosis_text"),
        })

    return results

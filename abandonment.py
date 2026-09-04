"""
abandonment.py - Checkout Abandonment Session Engine & Sweeper.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent
"""

import time
import logging
from typing import Dict, Any, List, Optional
from db import get_db
from abandonment_policy import (
    decide_abandonment_action,
    DEFAULT_ABANDON_WINDOW_SECONDS,
)
from executor import create_recovery_payment_link
from audit import log_decision
from llm_diagnostics import generate_diagnosis_and_copy

logger = logging.getLogger("recovery_agent.abandonment")


def create_or_update_session(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Creates or updates an active checkout session.
    """
    session_id = session_data["session_id"]
    order_id = session_data.get("order_id", "")
    amount_inr = float(session_data.get("amount_inr", 0.0))
    email = session_data.get("customer_email", "")
    contact = session_data.get("customer_contact", "")
    cart_step = session_data.get("cart_step", "cart")
    method = session_data.get("method_attempted", "upi")
    now = session_data.get("created_at", time.time())

    with get_db() as conn:
        conn.execute("""
            INSERT INTO checkout_sessions (
                session_id, order_id, amount_inr, customer_email, customer_contact,
                cart_step, method_attempted, created_at, nudge_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(session_id) DO UPDATE SET
                order_id = excluded.order_id,
                amount_inr = excluded.amount_inr,
                cart_step = excluded.cart_step,
                method_attempted = excluded.method_attempted
        """, (session_id, order_id, amount_inr, email, contact, cart_step, method, now))

    return get_session(session_id) or {}


def mark_session_completed(
    session_id: Optional[str] = None,
    order_id: Optional[str] = None,
    completed_at: Optional[float] = None,
) -> bool:
    """
    Marks a checkout session as completed/paid, halting further abandonment outreach.
    """
    ts = completed_at if completed_at is not None else time.time()
    with get_db() as conn:
        if session_id:
            cursor = conn.execute(
                "UPDATE checkout_sessions SET completed_at = ? WHERE session_id = ? AND completed_at IS NULL",
                (ts, session_id),
            )
        elif order_id:
            cursor = conn.execute(
                "UPDATE checkout_sessions SET completed_at = ? WHERE order_id = ? AND completed_at IS NULL",
                (ts, order_id),
            )
        else:
            return False

        updated = cursor.rowcount > 0
        if updated:
            logger.info("Checkout session marked completed for session_id=%s, order_id=%s", session_id, order_id)
        return updated


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a checkout session by session_id."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM checkout_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def sweep_abandoned_sessions(
    cutoff_seconds: int = DEFAULT_ABANDON_WINDOW_SECONDS,
    current_time: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Sweeps the database for uncompleted checkout sessions past the abandonment cutoff window.
    Applies abandonment policy, generates live Payment Links, and logs to the audit ledger.
    """
    now = current_time if current_time is not None else time.time()
    cutoff_ts = now - cutoff_seconds
    results = []

    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM checkout_sessions
            WHERE completed_at IS NULL AND created_at <= ?
            ORDER BY created_at ASC
        """, (cutoff_ts,)).fetchall()

    for r in rows:
        session = dict(r)
        decision = decide_abandonment_action(session, current_time=now)
        session_id = session["session_id"]

        feat = {
            "transaction_id": session_id,
            "order_id": session.get("order_id") or session_id,
            "amount": int(session.get("amount_inr", 0.0) * 100),
            "amount_inr": session.get("amount_inr", 0.0),
            "customer_email": session.get("customer_email"),
            "customer_contact": session.get("customer_contact"),
            "method": session.get("method_attempted"),
            "error_code": f"abandoned_{session.get('cart_step', 'cart')}",
            "prior_failures": session.get("nudge_count", 0),
            "timestamp": now,
        }

        # Generate LLM diagnostics & personalized cart recovery copy
        llm_out = generate_diagnosis_and_copy(
            features=feat,
            action=decision.action,
            rule=decision.rule_triggered,
            recovery_prob=decision.recovery_probability,
        )

        payment_link_id = None
        payment_link_url = None

        if decision.action in ("NUDGE_NOW", "NUDGE_DELAYED"):
            try:
                link_res = create_recovery_payment_link(feat)
                payment_link_id = link_res.get("id")
                payment_link_url = link_res.get("short_url")
            except Exception as e:
                logger.error("Failed to generate payment link for abandoned cart %s: %s", session_id, e)

            # Update session state in DB
            new_nudge_count = session.get("nudge_count", 0) + 1
            with get_db() as conn:
                conn.execute("""
                    UPDATE checkout_sessions
                    SET nudge_count = ?, last_nudge_ts = ?
                    WHERE session_id = ?
                """, (new_nudge_count, now, session_id))

        elif decision.action == "STOP":
            with get_db() as conn:
                conn.execute("""
                    UPDATE checkout_sessions
                    SET last_nudge_ts = COALESCE(last_nudge_ts, ?)
                    WHERE session_id = ?
                """, (now, session_id))

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
            recovery_type="checkout_abandonment",
        )

        results.append({
            "session_id": session_id,
            "action": decision.action,
            "rule": decision.rule_triggered,
            "payment_link": payment_link_url,
            "diagnosis": llm_out.get("diagnosis_text"),
        })

    return results

"""
app.py - Production-Ready FastAPI Webhook Receiver for Razorpay Test Mode.
Supports one-off payment recovery and subscription/mandate retry sequencing with idempotency.
"""

import hmac
import hashlib
import json
import logging
import os
import time
from typing import Set, Optional
from fastapi import FastAPI, Request, Header, HTTPException

from features import build_features, global_tracker
from policy import decide_action
from subscription_policy import decide_subscription_action
from executor import create_recovery_payment_link
from audit import log_decision
from llm_diagnostics import generate_diagnosis_and_copy
from db import init_db, is_event_processed, record_processed_event
from escalation import raise_escalation, get_escalations, resolve_escalation
from abandonment import create_or_update_session, mark_session_completed, sweep_abandoned_sessions
from receivables import (
    create_or_update_invoice,
    get_invoice,
    record_promise_to_pay,
    mark_invoice_paid,
    sweep_overdue_invoices,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recovery_agent")

# Initialize SQLite persistence tables
init_db()

app = FastAPI(title="Razorpay AI Revenue Recovery Agent")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    if not secret:
        logger.warning("WEBHOOK_SECRET not set; signature verification bypassed for testing")
        return True
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "Razorpay AI Revenue Recovery Agent",
        "features": [
            "one_off_payment_recovery",
            "subscription_mandate_sequencer",
            "event_idempotency",
            "llm_root_cause_diagnostics",
            "tamper_evident_audit_chain",
        ]
    }


@app.post("/webhook")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None),
):
    raw_body = await request.body()

    # 1. Signature Verification
    if WEBHOOK_SECRET and x_razorpay_signature is not None:
        if not verify_signature(raw_body, x_razorpay_signature, WEBHOOK_SECRET):
            logger.warning("Signature mismatch — rejecting webhook")
            raise HTTPException(status_code=400, detail="Invalid signature")
    elif WEBHOOK_SECRET and x_razorpay_signature is None:
        if os.getenv("STRICT_WEBHOOK_VERIFICATION", "").lower() == "true":
            raise HTTPException(status_code=400, detail="Missing signature header")
        logger.info("X-Razorpay-Signature omitted — permitted for manual local testing.")

    try:
        payload = json.loads(raw_body) if raw_body else {}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    event = payload.get("event")
    
    # 2. Webhook Event Idempotency Check (Prevents duplicate processing on Razorpay at-least-once retries)
    event_id = payload.get("id") or hashlib.sha256(raw_body).hexdigest()
    if is_event_processed(event_id):
        logger.info("Duplicate webhook event %s detected — skipping duplicate execution", event_id)
        return {
            "status": "duplicate_ignored",
            "event_id": event_id,
            "message": "Event already processed idempotently.",
        }
    record_processed_event(event_id)

    logger.info("Processing webhook event: %s (event_id=%s)", event, event_id)

    # ----------------------------------------------------
    # Case A: One-Off Payment Failure (payment.failed)
    # ----------------------------------------------------
    if event == "payment.failed":
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        
        features = build_features(entity, tracker=global_tracker)
        decision = decide_action(features)

        tracking_key = features["tracking_key"]
        global_tracker.record_failure(tracking_key)

        payment_link_id = None
        payment_link_url = None

        # LLM Root-Cause Diagnostics & Customer Outreach Copy
        llm_out = generate_diagnosis_and_copy(
            features=features,
            action=decision.action,
            rule=decision.rule_triggered,
            recovery_prob=decision.recovery_probability,
        )

        # Record the chosen action in tracker to maintain cooldown state
        global_tracker.record_action(tracking_key, decision.action)

        escalation_id = None
        if decision.action == "RETRY_LINK_NOW":
            try:
                link_res = create_recovery_payment_link(features)
                payment_link_id = link_res.get("id")
                payment_link_url = link_res.get("short_url")
                logger.info("Dispatched Payment Link %s", payment_link_url)
            except Exception as e:
                logger.error("Failed to dispatch payment link: %s", e)

        elif decision.action == "ESCALATE_HUMAN":
            escalation_id = raise_escalation(
                features=features,
                rule_triggered=decision.rule_triggered,
                explanation=decision.explanation,
                diagnosis_text=llm_out.get("diagnosis_text"),
            )

        # Record to hash-chained tamper-evident audit log
        log_decision(
            features=features,
            decision_action=decision.action,
            rule_triggered=decision.rule_triggered,
            recovery_probability=decision.recovery_probability,
            explanation=decision.explanation,
            diagnosis_text=llm_out["diagnosis_text"],
            customer_message=llm_out["customer_message"],
            payment_link_id=payment_link_id,
            payment_link_url=payment_link_url,
            recovery_type="one_off_payment",
        )

        return {
            "status": "ok",
            "recovery_type": "one_off_payment",
            "decision": decision.action,
            "rule": decision.rule_triggered,
            "payment_link": payment_link_url,
            "diagnosis": llm_out["diagnosis_text"],
            "customer_message": llm_out["customer_message"],
        }

    # ----------------------------------------------------
    # Case B: Subscription / Mandate Failure (subscription.charged.failed)
    # ----------------------------------------------------
    elif event in ("subscription.charged.failed", "subscription.halted", "invoice.payment_failed"):
        payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        sub_entity = payload.get("payload", {}).get("subscription", {}).get("entity", {})
        
        sub_id = sub_entity.get("id") if sub_entity else None
        features = build_features(payment_entity, tracker=global_tracker, custom_tracking_key=sub_id)
        if sub_id:
            features["subscription_id"] = sub_id

        sub_decision = decide_subscription_action(features)
        tracking_key = features["tracking_key"]
        global_tracker.record_failure(tracking_key)

        payment_link_id = None
        payment_link_url = None

        llm_out = generate_diagnosis_and_copy(
            features=features,
            action=sub_decision.action,
            rule=sub_decision.rule_triggered,
            recovery_prob=sub_decision.recovery_probability,
        )

        # Record the chosen action in tracker
        global_tracker.record_action(tracking_key, sub_decision.action)

        if sub_decision.action == "SEND_UPDATE_PAYMENT_METHOD_LINK":
            try:
                link_res = create_recovery_payment_link(features)
                payment_link_id = link_res.get("id")
                payment_link_url = link_res.get("short_url")
            except Exception as e:
                logger.error("Failed to create update payment method link: %s", e)
        elif sub_decision.action == "ESCALATE_HUMAN":
            raise_escalation(
                features=features,
                rule_triggered=sub_decision.rule_triggered,
                explanation=sub_decision.explanation,
                diagnosis_text=llm_out.get("diagnosis_text"),
            )

        log_decision(
            features=features,
            decision_action=sub_decision.action,
            rule_triggered=sub_decision.rule_triggered,
            recovery_probability=sub_decision.recovery_probability,
            explanation=sub_decision.explanation,
            diagnosis_text=llm_out["diagnosis_text"],
            customer_message=llm_out["customer_message"],
            payment_link_id=payment_link_id,
            payment_link_url=payment_link_url,
            recovery_type="subscription_mandate",
        )

        return {
            "status": "ok",
            "recovery_type": "subscription_mandate",
            "decision": sub_decision.action,
            "rule": sub_decision.rule_triggered,
            "retry_delay_days": sub_decision.retry_delay_days,
            "payment_link": payment_link_url,
            "diagnosis": llm_out["diagnosis_text"],
        }

    elif event in ("payment.authorized", "payment.captured", "subscription.charged", "order.paid"):
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        order_entity = payload.get("payload", {}).get("order", {}).get("entity", {})
        txn_id = entity.get("id")
        order_id = entity.get("order_id") or order_entity.get("id")
        if order_id:
            mark_session_completed(order_id=order_id)
        logger.info("Payment confirmed / order paid: txn=%s, order=%s", txn_id, order_id)
        return {"status": "ok", "recovered_transaction_id": txn_id, "order_id": order_id}

    return {"status": "ok"}


# ----------------------------------------------------------------------
# Human Escalation Operational Endpoints (Priority 2)
# ----------------------------------------------------------------------

@app.get("/escalations")
def list_escalations(status: Optional[str] = "open"):
    """Lists queued human escalations (status filter: 'open', 'resolved', or omit for all)."""
    return {"escalations": get_escalations(status)}


@app.post("/escalations/{escalation_id}/resolve")
async def resolve_escalation_endpoint(escalation_id: int, request: Request):
    """Allows human agents to mark an escalation as resolved with notes and audit logging."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    notes = body.get("notes", "Resolved via operations portal")
    resolver = body.get("resolver", "human_operator")
    res = resolve_escalation(escalation_id, notes=notes, resolver=resolver)
    if not res:
        raise HTTPException(status_code=404, detail=f"Escalation {escalation_id} not found")
    return {"status": "resolved", "escalation": res}


# ----------------------------------------------------------------------
# Checkout Abandonment Endpoints (Priority 3)
# ----------------------------------------------------------------------

@app.post("/checkout/session")
async def register_checkout_session(request: Request):
    """Registers or updates an active customer checkout session."""
    data = await request.json()
    session = create_or_update_session(data)
    return {"status": "ok", "session": session}


@app.post("/checkout/sweep")
def sweep_checkout_endpoint(cutoff_seconds: int = 900):
    """Triggers an on-demand sweep for abandoned checkout sessions past the cutoff window."""
    results = sweep_abandoned_sessions(cutoff_seconds=cutoff_seconds)
    return {"status": "ok", "swept_count": len(results), "results": results}


# ----------------------------------------------------------------------
# B2B Receivables & Promise-to-Pay Endpoints (Priority 4)
# ----------------------------------------------------------------------

@app.post("/invoices")
async def create_invoice_endpoint(request: Request):
    """Creates or updates a B2B invoice in the system."""
    data = await request.json()
    invoice = create_or_update_invoice(data)
    return {"status": "ok", "invoice": invoice}


@app.get("/invoices/{invoice_id}")
def get_invoice_endpoint(invoice_id: str):
    """Fetches status, dunning stage, and promise details for a specific invoice."""
    inv = get_invoice(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
    return {"status": "ok", "invoice": inv}


@app.post("/invoices/{invoice_id}/promise")
async def record_promise_endpoint(invoice_id: str, request: Request):
    """Records a customer commitment to pay by a specified date, pausing automated dunning."""
    data = await request.json()
    promised_ts = float(data.get("promised_date", time.time() + 86400 * 7))
    updated = record_promise_to_pay(invoice_id, promised_ts)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
    return {"status": "ok", "invoice": updated}


@app.post("/invoices/{invoice_id}/pay")
def mark_paid_endpoint(invoice_id: str):
    """Marks an invoice as paid in full, permanently terminating dunning outreach."""
    updated = mark_invoice_paid(invoice_id)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
    return {"status": "ok", "invoice": updated}


@app.post("/invoices/sweep")
def sweep_invoices_endpoint(min_contact_gap_seconds: Optional[float] = None):
    """Triggers an on-demand dunning sweep across all active overdue B2B invoices."""
    results = sweep_overdue_invoices(min_contact_gap_seconds=min_contact_gap_seconds)
    return {"status": "ok", "swept_count": len(results), "results": results}
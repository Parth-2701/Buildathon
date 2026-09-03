"""
app.py - Production-Ready FastAPI Webhook Receiver for Razorpay Test Mode.
Supports one-off payment recovery and subscription/mandate retry sequencing with idempotency.
"""

import hmac
import hashlib
import json
import logging
import os
from typing import Set
from fastapi import FastAPI, Request, Header, HTTPException

from features import build_features, global_tracker
from policy import decide_action
from subscription_policy import decide_subscription_action
from executor import create_recovery_payment_link
from audit import log_decision
from llm_diagnostics import generate_diagnosis_and_copy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recovery_agent")

app = FastAPI(title="Razorpay AI Revenue Recovery Agent")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

# In-memory webhook event idempotency cache to prevent duplicate processing
_PROCESSED_EVENT_IDS: Set[str] = set()


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
    if WEBHOOK_SECRET and x_razorpay_signature is None:
        raise HTTPException(status_code=400, detail="Missing signature header")

    if WEBHOOK_SECRET and not verify_signature(raw_body, x_razorpay_signature, WEBHOOK_SECRET):
        logger.warning("Signature mismatch — rejecting webhook")
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = json.loads(raw_body)
    event = payload.get("event")
    
    # 2. Webhook Event Idempotency Check (Prevents duplicate processing on Razorpay at-least-once retries)
    event_id = payload.get("id") or hashlib.sha256(raw_body).hexdigest()
    if event_id in _PROCESSED_EVENT_IDS:
        logger.info("Duplicate webhook event %s detected — skipping duplicate execution", event_id)
        return {
            "status": "duplicate_ignored",
            "event_id": event_id,
            "message": "Event already processed idempotently.",
        }
    _PROCESSED_EVENT_IDS.add(event_id)

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

        if decision.action == "RETRY_LINK_NOW":
            try:
                link_res = create_recovery_payment_link(features)
                payment_link_id = link_res.get("id")
                payment_link_url = link_res.get("short_url")
                logger.info("Dispatched Payment Link %s", payment_link_url)
            except Exception as e:
                logger.error("Failed to dispatch payment link: %s", e)

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

    elif event in ("payment.authorized", "payment.captured", "subscription.charged"):
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        txn_id = entity.get("id")
        logger.info("Payment confirmed settled: %s (amount=%s)", txn_id, entity.get("amount"))
        return {"status": "ok", "recovered_transaction_id": txn_id}

    return {"status": "ok"}
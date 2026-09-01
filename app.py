"""
Minimal FastAPI webhook receiver for Razorpay Test Mode.
Run with: uvicorn app:app --port 5000 --reload
"""

import hmac
import hashlib
import json
import logging
import os
from fastapi import FastAPI, Request, Header, HTTPException

from features import build_features, global_tracker
from policy import decide_action
from executor import create_recovery_payment_link
from audit import log_decision

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recovery_agent")

app = FastAPI(title="Razorpay AI Revenue Recovery Agent")

# Paste the secret you set when creating the webhook in the Razorpay dashboard
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    if not secret:
        # Development warning if secret not configured
        logger.warning("WEBHOOK_SECRET not set; signature verification bypassed for testing")
        return True
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.get("/health")
def health():
    return {"status": "healthy", "service": "AI Revenue Recovery Agent"}


@app.post("/webhook")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None),
):
    raw_body = await request.body()  # must read raw bytes, not parsed JSON

    if WEBHOOK_SECRET and x_razorpay_signature is None:
        raise HTTPException(status_code=400, detail="Missing signature header")

    if WEBHOOK_SECRET and not verify_signature(raw_body, x_razorpay_signature, WEBHOOK_SECRET):
        logger.warning("Signature mismatch — rejecting webhook")
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = json.loads(raw_body)
    event = payload.get("event")
    logger.info("Received event: %s", event)

    if event == "payment.failed":
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        
        # 1. Extract and build structured features
        features = build_features(entity, tracker=global_tracker)
        logger.info(
            "Extracted features for txn=%s: error_code=%s, amount=₹%.2f, prior_failures=%d",
            features["transaction_id"],
            features["error_code"],
            features["amount_inr"],
            features["prior_failures"],
        )

        # 2. Evaluate Policy Engine (Day 2 rules)
        decision = decide_action(features)
        logger.info(
            "Decision: action=%s | rule=%s | prob=%.2f | reason=%s",
            decision.action,
            decision.rule_triggered,
            decision.recovery_probability,
            decision.explanation,
        )

        # Record this failure in the tracker
        tracking_key = features["tracking_key"]
        global_tracker.record_failure(tracking_key)

        payment_link_id = None
        payment_link_url = None

        # 3. Action Dispatcher
        if decision.action == "RETRY_LINK_NOW":
            try:
                link_res = create_recovery_payment_link(features)
                payment_link_id = link_res.get("id")
                payment_link_url = link_res.get("short_url")
                global_tracker.record_action(tracking_key, "RETRY_LINK_NOW")
                logger.info("Action dispatched: Created Payment Link %s", payment_link_url)
            except Exception as e:
                logger.error("Failed to dispatch payment link: %s", e)

        elif decision.action == "RETRY_LINK_DELAYED":
            global_tracker.record_action(tracking_key, "RETRY_LINK_DELAYED")
            logger.info("Action scheduled: Delayed outreach queued for txn=%s", features["transaction_id"])

        elif decision.action == "ESCALATE_HUMAN":
            global_tracker.record_action(tracking_key, "ESCALATE_HUMAN")
            logger.info("Action recorded: Escalated to human support for txn=%s", features["transaction_id"])

        elif decision.action == "STOP":
            global_tracker.record_action(tracking_key, "STOP")
            logger.info("Action recorded: Recovery stopped permanently for txn=%s", features["transaction_id"])

        # 4. Audit Log
        audit_entry = log_decision(
            features=features,
            decision_action=decision.action,
            rule_triggered=decision.rule_triggered,
            recovery_probability=decision.recovery_probability,
            explanation=decision.explanation,
            payment_link_id=payment_link_id,
            payment_link_url=payment_link_url,
        )

        return {
            "status": "ok",
            "decision": decision.action,
            "rule": decision.rule_triggered,
            "payment_link": payment_link_url,
        }

    elif event in ("payment.authorized", "payment.captured"):
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        txn_id = entity.get("id")
        logger.info("%s | id=%s amount=%s", event, txn_id, entity.get("amount"))
        # In audit log / tracker, mark as successfully recovered if linked to a previous failed attempt
        return {"status": "ok", "recovered_transaction_id": txn_id}

    # Razorpay requires a 2xx response within 5 seconds or it counts as a failure
    return {"status": "ok"}
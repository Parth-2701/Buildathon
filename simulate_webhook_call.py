"""
simulate_webhook_call.py - Sends simulated Razorpay webhooks through the FastAPI app.
Validates the full end-to-end flow: Webhook -> Features -> Policy -> Payment Link / Action -> Audit Log
"""

import json
from app import app
from fastapi.testclient import TestClient

client = TestClient(app)

scenarios = [
    {
        "name": "Scenario 1: Transient Error (Network/Gateway Timeout) -> Immediate Payment Link",
        "entity": {
            "id": "pay_scenario_1_transient",
            "amount": 450000,  # INR 4,500
            "currency": "INR",
            "method": "card",
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "gateway_technical_error",
            "error_description": "Bank gateway connection timeout",
            "email": "customer1@example.com",
            "contact": "+919876543210",
        },
    },
    {
        "name": "Scenario 2: Hard Decline (Stolen Card) -> Compliant Human Escalation (No Auto Link)",
        "entity": {
            "id": "pay_scenario_2_stolen",
            "amount": 120000,  # INR 1,200
            "currency": "INR",
            "method": "card",
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "stolen_card",
            "error_description": "Card reported stolen by issuing bank",
            "email": "fraud.alert@example.com",
            "contact": "+919876543210",
        },
    },
    {
        "name": "Scenario 3: High Ticket Amount (> INR 10,000) -> Human Escalation Ceiling",
        "entity": {
            "id": "pay_scenario_3_high_value",
            "amount": 2500000,  # INR 25,000
            "currency": "INR",
            "method": "card",
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "payment_timed_out",
            "error_description": "Timed out waiting for OTP",
            "email": "vip.buyer@example.com",
            "contact": "+919876543210",
        },
    },
    {
        "name": "Scenario 4: Soft Failure (Insufficient Funds) -> Delayed Retry Nudge",
        "entity": {
            "id": "pay_scenario_4_low_funds",
            "amount": 99900,  # INR 999
            "currency": "INR",
            "method": "upi",
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "insufficient_funds",
            "error_description": "Balance not available",
            "email": "user4@example.com",
            "contact": "+919876543210",
        },
    },
    {
        "name": "Scenario 5: Max Retries Stopping Rule (Same Txn Failing 3 Times) -> STOP",
        "entity": {
            "id": "pay_scenario_1_transient",  # Same ID from scenario 1, now on attempt 3
            "amount": 450000,
            "currency": "INR",
            "method": "card",
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "gateway_technical_error",
            "error_description": "Still failing",
            "email": "customer1@example.com",
            "contact": "+919876543210",
        },
    },
]

print("\n========================================================")
print(" RUNNING END-TO-END WEBHOOK SIMULATION")
print("========================================================")

import hmac
import hashlib
import os
from dotenv import load_dotenv

load_dotenv()
webhook_secret = os.getenv("WEBHOOK_SECRET")

import time

for scenario in scenarios:
    ts = int(time.time() * 1000)
    entity = dict(scenario["entity"])
    entity["id"] = f"{scenario['entity']['id']}_{ts}"

    print(f"\n>> {scenario['name']}")
    webhook_payload = {
        "id": f"evt_sim_{ts}_{scenario['entity']['id']}",
        "entity": "event",
        "account_id": "acc_buildathon_demo",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": entity
            }
        },
    }

    raw_bytes = json.dumps(webhook_payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if webhook_secret:
        sig = hmac.new(webhook_secret.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()
        headers["X-Razorpay-Signature"] = sig

    res = client.post(
        "/webhook",
        content=raw_bytes,
        headers=headers,
    )
    data = res.json()
    print(f"   Status Code  : {res.status_code}")
    print(f"   Action Taken : {data.get('decision')}")
    print(f"   Rule Fired   : {data.get('rule')}")
    if data.get('payment_link'):
        print(f"   Payment Link : {data.get('payment_link')}")

print("\n========================================================")
print(" SIMULATION COMPLETE. Inspecting audit_log.csv...")
print("========================================================")

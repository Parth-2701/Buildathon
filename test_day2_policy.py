"""
test_day2_policy.py - Validation test suite for Day 2 Rule-Based Policy Engine & Webhook Flow.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent
"""

import os
import json
import pytest
from fastapi.testclient import TestClient

from constants import (
    ACTIONS,
    HARD_DECLINE_CODES,
    MAX_AUTO_RETRIES,
    AMOUNT_ESCALATION_THRESHOLD,
)
from features import build_features, TransactionTracker, normalize_error_code
from policy import decide_action
from app import app
import audit


def test_normalize_error_code():
    assert normalize_error_code("gateway_technical_error", None) == "gateway_technical_error"
    assert normalize_error_code(None, "BAD_REQUEST_ERROR") == "bad_request_error"
    assert normalize_error_code("Card Lost Or Stolen", None) == "card_lost_or_stolen"


def test_features_and_tracking():
    tracker = TransactionTracker()
    dummy_payload = {
        "id": "pay_test_001",
        "amount": 250000,  # ₹2,500
        "currency": "INR",
        "method": "card",
        "error_code": "BAD_REQUEST_ERROR",
        "error_reason": "payment_timed_out",
        "email": "user@example.com",
        "contact": "+919876543210",
    }
    
    # 1st attempt: 0 prior failures
    f1 = build_features(dummy_payload, tracker=tracker)
    assert f1["transaction_id"] == "pay_test_001"
    assert f1["prior_failures"] == 0
    assert f1["amount_inr"] == 2500.0
    assert f1["error_code"] == "payment_timed_out"
    assert f1["is_in_cooldown"] is False

    # Simulate recording failure & action
    tracker.record_failure("pay_test_001")
    tracker.record_action("pay_test_001", "RETRY_LINK_NOW")

    # 2nd attempt right away: should show prior_failures=1 and is_in_cooldown=True
    f2 = build_features(dummy_payload, tracker=tracker)
    assert f2["prior_failures"] == 1
    assert f2["is_in_cooldown"] is True


def test_policy_decisions():
    # Test Case 1: Transient error, low amount -> RETRY_LINK_NOW
    f1 = {
        "error_code": "gateway_technical_error",
        "amount": 100000,  # ₹1,000
        "prior_failures": 0,
        "is_in_cooldown": False,
    }
    d1 = decide_action(f1)
    assert d1.action == "RETRY_LINK_NOW"
    assert d1.rule_triggered == "RULE_HIGH_PROB_IMMEDIATE_RETRY"

    # Test Case 2: Insufficient funds (recovery prob 0.35 < 0.40) -> RETRY_LINK_DELAYED
    f2 = {
        "error_code": "insufficient_funds",
        "amount": 100000,
        "prior_failures": 0,
        "is_in_cooldown": False,
    }
    d2 = decide_action(f2)
    assert d2.action == "RETRY_LINK_DELAYED"
    assert d2.rule_triggered == "RULE_LOW_PROB_DELAYED_NUDGE"

    # Test Case 3: Hard decline codes -> ESCALATE_HUMAN (must never auto-retry)
    for code in HARD_DECLINE_CODES:
        f_hard = {
            "error_code": code,
            "amount": 50000,
            "prior_failures": 0,
            "is_in_cooldown": False,
        }
        d_hard = decide_action(f_hard)
        assert d_hard.action == "ESCALATE_HUMAN", f"Failed for {code}"
        assert d_hard.rule_triggered == "RULE_HARD_DECLINE_COMPLIANCE"
        assert d_hard.recovery_probability == 0.0

    # Test Case 4: High amount exposure (> ₹10,000) -> ESCALATE_HUMAN
    f_high = {
        "error_code": "gateway_technical_error",
        "amount": AMOUNT_ESCALATION_THRESHOLD + 100,  # > ₹10,000
        "prior_failures": 0,
        "is_in_cooldown": False,
    }
    d_high = decide_action(f_high)
    assert d_high.action == "ESCALATE_HUMAN"
    assert d_high.rule_triggered == "RULE_HIGH_AMOUNT_ESCALATION"

    # Test Case 5: Stopping Rule - Max Retries Ceiling (>= 2) -> STOP
    f_stop = {
        "error_code": "gateway_technical_error",
        "amount": 100000,
        "prior_failures": MAX_AUTO_RETRIES,
        "is_in_cooldown": False,
    }
    d_stop = decide_action(f_stop)
    assert d_stop.action == "STOP"
    assert d_stop.rule_triggered == "RULE_MAX_RETRIES_EXCEEDED"

    # Test Case 6: Stopping Rule - Cooldown active -> STOP
    f_cooldown = {
        "error_code": "gateway_technical_error",
        "amount": 100000,
        "prior_failures": 1,
        "is_in_cooldown": True,
        "seconds_since_last_action": 120,
    }
    d_cooldown = decide_action(f_cooldown)
    assert d_cooldown.action == "STOP"
    assert d_cooldown.rule_triggered == "RULE_COOLDOWN_ACTIVE"


def test_app_webhook_end_to_end(tmp_path):
    # Set a temporary audit log file
    temp_audit_file = str(tmp_path / "test_audit.csv")
    audit.init_audit_log(temp_audit_file)

    client = TestClient(app)

    # Health check
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "healthy"

    # Post payment.failed webhook
    payload = {
        "entity": "event",
        "account_id": "acc_test",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_live_test_001",
                    "amount": 49900,  # ₹499.00
                    "currency": "INR",
                    "status": "failed",
                    "method": "card",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_reason": "gateway_technical_error",
                    "error_description": "Gateway connection error",
                    "email": "customer@example.com",
                    "contact": "+919876543210",
                }
            }
        },
    }

    response = client.post(
        "/webhook",
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["decision"] == "RETRY_LINK_NOW"
    assert data["rule"] == "RULE_HIGH_PROB_IMMEDIATE_RETRY"


if __name__ == "__main__":
    pytest.main(["-v", __file__])

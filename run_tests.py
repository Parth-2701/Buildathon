"""
run_tests.py - Comprehensive test runner validating Day 1, Day 2, and Day 3 implementations.
"""

import os
import sys
import json
import pandas as pd

from constants import (
    ACTIONS,
    HARD_DECLINE_CODES,
    MAX_AUTO_RETRIES,
    AMOUNT_ESCALATION_THRESHOLD,
    ORACLE_PROBS,
    EMPIRICAL_FAILURE_WEIGHTS,
)
from features import build_features, TransactionTracker, normalize_error_code
from policy import decide_action
from model import predict_recovery_probability, train_and_evaluate, get_model
from simulate import generate_batch
import audit


def run_all_tests():
    passed = 0
    total = 0

    def check(condition, desc):
        nonlocal passed, total
        total += 1
        if condition:
            passed += 1
            print(f"  [PASS] {desc}")
        else:
            print(f"  [FAIL] {desc}")
            sys.exit(1)

    print("\n--- 1. Testing Normalization & Feature Builder ---")
    check(normalize_error_code("gateway_technical_error", None) == "gateway_technical_error", "Normalize error reason")
    check(normalize_error_code(None, "BAD_REQUEST_ERROR") == "bad_request_error", "Normalize error code")
    check(normalize_error_code("Card Lost Or Stolen", None) == "card_lost_or_stolen", "Normalize mixed case & spaces")

    tracker = TransactionTracker()
    payload = {
        "id": "pay_test_001",
        "amount": 250000,
        "currency": "INR",
        "method": "card",
        "error_code": "BAD_REQUEST_ERROR",
        "error_reason": "payment_timed_out",
        "email": "user@example.com",
        "contact": "+919876543210",
    }
    f1 = build_features(payload, tracker=tracker)
    check(f1["transaction_id"] == "pay_test_001", "Extracted transaction_id")
    check(f1["amount_inr"] == 2500.0, "Converted amount to INR correctly")
    check(f1["prior_failures"] == 0, "Initial prior_failures is 0")
    check(f1["is_in_cooldown"] is False, "Initially not in cooldown")

    tracker.record_failure("pay_test_001")
    tracker.record_action("pay_test_001", "RETRY_LINK_NOW")
    f2 = build_features(payload, tracker=tracker)
    check(f2["prior_failures"] == 1, "prior_failures incremented to 1")
    check(f2["is_in_cooldown"] is True, "Cooldown triggered after action")

    print("\n--- 2. Testing Policy Decisions & Stopping Rules ---")
    # Immediate retry for transient error
    d1 = decide_action({
        "error_code": "gateway_technical_error",
        "amount": 100000,
        "prior_failures": 0,
        "is_in_cooldown": False,
    })
    check(d1.action == "RETRY_LINK_NOW" and d1.rule_triggered == "RULE_HIGH_PROB_IMMEDIATE_RETRY", "High probability transient -> RETRY_LINK_NOW")

    # Delayed retry for insufficient funds
    d2 = decide_action({
        "error_code": "insufficient_funds",
        "amount": 100000,
        "prior_failures": 0,
        "is_in_cooldown": False,
    })
    check(d2.action == "RETRY_LINK_DELAYED" and d2.rule_triggered == "RULE_LOW_PROB_DELAYED_NUDGE", "Low probability soft decline -> RETRY_LINK_DELAYED")

    # Hard declines -> ESCALATE_HUMAN (must never auto-retry)
    hard_all_escalate = True
    for code in HARD_DECLINE_CODES:
        d_hard = decide_action({
            "error_code": code,
            "amount": 50000,
            "prior_failures": 0,
            "is_in_cooldown": False,
        })
        if d_hard.action != "ESCALATE_HUMAN" or d_hard.rule_triggered != "RULE_HARD_DECLINE_COMPLIANCE":
            hard_all_escalate = False
    check(hard_all_escalate, f"All {len(HARD_DECLINE_CODES)} hard decline codes strictly escalate to human")

    # High value transaction escalation (> INR 10,000)
    d_high = decide_action({
        "error_code": "gateway_technical_error",
        "amount": AMOUNT_ESCALATION_THRESHOLD + 100,
        "prior_failures": 0,
        "is_in_cooldown": False,
    })
    check(d_high.action == "ESCALATE_HUMAN" and d_high.rule_triggered == "RULE_HIGH_AMOUNT_ESCALATION", "High amount (> INR 10,000) escalates to human")

    # Stopping rule: max retries
    d_stop = decide_action({
        "error_code": "gateway_technical_error",
        "amount": 100000,
        "prior_failures": MAX_AUTO_RETRIES,
        "is_in_cooldown": False,
    })
    check(d_stop.action == "STOP" and d_stop.rule_triggered == "RULE_MAX_RETRIES_EXCEEDED", "Prior failures >= 2 triggers hard STOP")

    # Stopping rule: active cooldown
    d_cooldown = decide_action({
        "error_code": "gateway_technical_error",
        "amount": 100000,
        "prior_failures": 1,
        "is_in_cooldown": True,
        "seconds_since_last_action": 120,
    })
    check(d_cooldown.action == "STOP" and d_cooldown.rule_triggered == "RULE_COOLDOWN_ACTIVE", "Active cooldown triggers STOP")

    print("\n--- 3. Testing Audit Logging ---")
    test_audit_path = "test_audit_log.csv"
    if os.path.exists(test_audit_path):
        os.remove(test_audit_path)

    audit.log_decision(
        features=f1,
        decision_action="RETRY_LINK_NOW",
        rule_triggered="RULE_HIGH_PROB_IMMEDIATE_RETRY",
        recovery_probability=0.70,
        explanation="Test explanation",
        payment_link_id="plink_test123",
        payment_link_url="https://rzp.io/i/test123",
        file_path=test_audit_path,
    )
    check(os.path.exists(test_audit_path), "Audit log file created")
    with open(test_audit_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        check(len(lines) == 2, "Audit log header + 1 record written")
        check("plink_test123" in lines[1] and "RULE_HIGH_PROB_IMMEDIATE_RETRY" in lines[1], "Audit log fields recorded accurately")

    if os.path.exists(test_audit_path):
        os.remove(test_audit_path)

    print("\n--- 4. Testing Day 3 ML Simulation & Recovery Model ---")
    # Test batch generation
    syn_df = generate_batch(n=500, seed=123)
    check(len(syn_df) == 500, "Synthetic batch generates correct row count (500)")
    check("true_recovery_prob" in syn_df.columns and "recovered" in syn_df.columns, "Synthetic batch contains expected columns")
    check(set(syn_df["error_code"].unique()).issubset(set(EMPIRICAL_FAILURE_WEIGHTS.keys())), "All generated error codes valid")

    # Test ML model predictions
    p_transient = predict_recovery_probability({"error_code": "gateway_technical_error", "method": "card", "amount_inr": 1000.0, "prior_failures": 0})
    check(p_transient >= 0.50, f"ML predicts high recovery for transient error (got {p_transient:.2%})")

    p_insufficient = predict_recovery_probability({"error_code": "insufficient_funds", "method": "upi", "amount_inr": 1000.0, "prior_failures": 0})
    check(p_insufficient < 0.40, f"ML predicts low recovery for insufficient funds (got {p_insufficient:.2%})")

    p_stolen = predict_recovery_probability({"error_code": "stolen_card", "method": "card", "amount_inr": 1000.0, "prior_failures": 0})
    check(p_stolen == 0.0, "ML strict compliance check returns 0.0 for hard decline error")

    # Prior failure decay check
    p_prior_0 = predict_recovery_probability({"error_code": "gateway_technical_error", "method": "card", "amount_inr": 1000.0, "prior_failures": 0})
    p_prior_1 = predict_recovery_probability({"error_code": "gateway_technical_error", "method": "card", "amount_inr": 1000.0, "prior_failures": 1})
    check(p_prior_0 >= p_prior_1, "ML accounts for diminishing returns on repeated failures")

    # Model fallback check (unknown error code)
    p_unknown = predict_recovery_probability({"error_code": "unrecognized_bank_code", "method": "card", "amount_inr": 500.0, "prior_failures": 0})
    check(0.0 <= p_unknown <= 1.0, f"Fallback returns valid bounded probability for unknown code (got {p_unknown})")

    print(f"\n==========================================")
    print(f" ALL TESTS PASSED: {passed}/{total}")
    print(f"==========================================\n")


if __name__ == "__main__":
    run_all_tests()

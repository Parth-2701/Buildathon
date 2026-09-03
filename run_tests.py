"""
run_tests.py - Comprehensive test runner validating full pipeline, enhancements, and safety guardrails.
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
from subscription_policy import decide_subscription_action, SUBSCRIPTION_ACTIONS
from model import predict_recovery_probability, get_model
from simulate import generate_batch
from llm_diagnostics import generate_diagnosis_and_copy
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
    d1 = decide_action({
        "error_code": "gateway_technical_error",
        "amount": 100000,
        "prior_failures": 0,
        "is_in_cooldown": False,
    })
    check(d1.action == "RETRY_LINK_NOW" and d1.rule_triggered == "RULE_HIGH_PROB_IMMEDIATE_RETRY", "High probability transient -> RETRY_LINK_NOW")

    d2 = decide_action({
        "error_code": "insufficient_funds",
        "amount": 100000,
        "prior_failures": 0,
        "is_in_cooldown": False,
    })
    check(d2.action == "RETRY_LINK_DELAYED" and d2.rule_triggered == "RULE_LOW_PROB_DELAYED_NUDGE", "Low probability soft decline -> RETRY_LINK_DELAYED")

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

    d_high = decide_action({
        "error_code": "gateway_technical_error",
        "amount": AMOUNT_ESCALATION_THRESHOLD + 100,
        "prior_failures": 0,
        "is_in_cooldown": False,
    })
    check(d_high.action == "ESCALATE_HUMAN" and d_high.rule_triggered == "RULE_HIGH_AMOUNT_ESCALATION", "High amount (> INR 10,000) escalates to human")

    d_stop = decide_action({
        "error_code": "gateway_technical_error",
        "amount": 100000,
        "prior_failures": MAX_AUTO_RETRIES,
        "is_in_cooldown": False,
    })
    check(d_stop.action == "STOP" and d_stop.rule_triggered == "RULE_MAX_RETRIES_EXCEEDED", "Prior failures >= 2 triggers hard STOP")

    d_cooldown = decide_action({
        "error_code": "gateway_technical_error",
        "amount": 100000,
        "prior_failures": 1,
        "is_in_cooldown": True,
        "seconds_since_last_action": 120,
    })
    check(d_cooldown.action == "STOP" and d_cooldown.rule_triggered == "RULE_COOLDOWN_ACTIVE", "Active cooldown triggers STOP")

    print("\n--- 3. Testing Hash-Chained Audit Trail & Tamper Detection ---")
    test_audit_path = "test_audit_chain.csv"
    if os.path.exists(test_audit_path):
        os.remove(test_audit_path)

    # Write 3 chained records
    r1 = audit.log_decision(f1, "RETRY_LINK_NOW", "RULE_HIGH_PROB_IMMEDIATE_RETRY", 0.70, explanation="Exp 1", file_path=test_audit_path)
    r2 = audit.log_decision(f2, "STOP", "RULE_COOLDOWN_ACTIVE", 0.0, explanation="Exp 2", file_path=test_audit_path)
    r3 = audit.log_decision(f1, "ESCALATE_HUMAN", "RULE_HARD_DECLINE_COMPLIANCE", 0.0, explanation="Exp 3", file_path=test_audit_path)

    is_valid, count, err = audit.verify_audit_log_integrity(test_audit_path)
    check(is_valid and count == 3, "Cryptographic hash chain validated across all 3 audit entries")

    # Simulate malicious tampering in audit file
    with open(test_audit_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    # Modify amount in row 2
    lines[2] = lines[2].replace("2500.00", "9999.00")
    with open(test_audit_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    is_valid_after_tamper, _, err_msg = audit.verify_audit_log_integrity(test_audit_path)
    check(not is_valid_after_tamper and "Tampering detected" in err_msg, "Tamper-evident verification successfully caught corrupted audit row")

    if os.path.exists(test_audit_path):
        os.remove(test_audit_path)

    print("\n--- 4. Testing ML Simulation & Recovery Model ---")
    syn_df = generate_batch(n=500, seed=123)
    check(len(syn_df) == 500, "Synthetic batch generates correct row count (500)")
    check("true_recovery_prob" in syn_df.columns and "recovered" in syn_df.columns, "Synthetic batch contains expected columns")

    p_transient = predict_recovery_probability({"error_code": "gateway_technical_error", "method": "card", "amount_inr": 1000.0, "prior_failures": 0})
    check(p_transient >= 0.50, f"ML predicts high recovery for transient error (got {p_transient:.2%})")

    p_insufficient = predict_recovery_probability({"error_code": "insufficient_funds", "method": "upi", "amount_inr": 1000.0, "prior_failures": 0})
    check(p_insufficient < 0.40, f"ML predicts low recovery for insufficient funds (got {p_insufficient:.2%})")

    p_stolen = predict_recovery_probability({"error_code": "stolen_card", "method": "card", "amount_inr": 1000.0, "prior_failures": 0})
    check(p_stolen == 0.0, "ML strict compliance check returns 0.0 for hard decline error")

    print("\n--- 5. Testing LLM Diagnostics & Customer Copy Layer ---")
    diag_res = generate_diagnosis_and_copy(f1, "RETRY_LINK_NOW", "RULE_HIGH_PROB_IMMEDIATE_RETRY", 0.70)
    check("diagnosis_text" in diag_res and len(diag_res["diagnosis_text"]) > 10, "Generated internal diagnosis text")
    check("customer_message" in diag_res and len(diag_res["customer_message"]) > 10, "Generated customer outreach copy")

    print("\n--- 6. Testing Subscription & Mandate Retry Sequencing ---")
    # Sub case 1: 1st transient failure -> Schedule Day 1
    sub_1 = decide_subscription_action({"error_code": "gateway_technical_error", "amount": 99900, "prior_failures": 0, "is_in_cooldown": False})
    check(sub_1.action == "SCHEDULE_RETRY_DAY_1" and sub_1.retry_delay_days == 1, "Subscription 1st transient failure schedules Stage 1 (Day 1)")

    # Sub case 2: 2nd failure -> Schedule Day 3
    sub_2 = decide_subscription_action({"error_code": "insufficient_funds", "amount": 99900, "prior_failures": 1, "is_in_cooldown": False})
    check(sub_2.action == "SCHEDULE_RETRY_DAY_3" and sub_2.retry_delay_days == 3, "Subscription 2nd failure schedules Stage 2 (Day 3)")

    # Sub case 3: 3rd failure -> Schedule Day 7
    sub_3 = decide_subscription_action({"error_code": "insufficient_funds", "amount": 99900, "prior_failures": 2, "is_in_cooldown": False})
    check(sub_3.action == "SCHEDULE_DAY_7" or sub_3.action == "SCHEDULE_RETRY_DAY_7", "Subscription 3rd failure schedules Stage 3 (Day 7)")

    # Sub case 4: 4th failure (>= 3 prior) -> Cancel / Stop
    sub_4 = decide_subscription_action({"error_code": "insufficient_funds", "amount": 99900, "prior_failures": 3, "is_in_cooldown": False})
    check(sub_4.action == "CANCEL_SUBSCRIPTION_STOP", "Subscription exceeding max retries halts mandate attempts (STOP)")

    # Sub case 5: Expired card -> Send update payment method link
    sub_5 = decide_subscription_action({"error_code": "card_expired", "amount": 99900, "prior_failures": 0, "is_in_cooldown": False})
    check(sub_5.action == "SEND_UPDATE_PAYMENT_METHOD_LINK", "Expired subscription card triggers update payment method link")

    print(f"\n==========================================")
    print(f" ALL TESTS PASSED: {passed}/{total}")
    print(f"==========================================\n")


if __name__ == "__main__":
    run_all_tests()

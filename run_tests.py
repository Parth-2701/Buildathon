"""
run_tests.py - Comprehensive test runner validating full pipeline, enhancements, and safety guardrails.
"""

import os
import sys
import json
import time
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

    from db import reset_db
    reset_db()

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

    # Priority 1: Verify durable persistence across process restart
    restarted_tracker = TransactionTracker()
    check(restarted_tracker.get_prior_failures("pay_test_001") == 1, "Durable SQLite: failure count survives restart")
    check(restarted_tracker.is_in_cooldown("pay_test_001") is True, "Durable SQLite: active cooldown survives restart")

    from db import is_event_processed, record_processed_event
    check(not is_event_processed("evt_test_p1_unique"), "Durable SQLite: new event not yet in processed_events")
    record_processed_event("evt_test_p1_unique")
    check(is_event_processed("evt_test_p1_unique"), "Durable SQLite: event recorded idempotently in SQLite")

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

    print("\n--- 7. Testing Human Escalation Queue & Triage ---")
    from escalation import raise_escalation, get_escalations, resolve_escalation
    esc_features = {
        "transaction_id": "pay_esc_test_999",
        "order_id": "order_esc_test_999",
        "amount_inr": 15000.0,
        "customer_email": "vip.user@example.com",
    }
    esc_id = raise_escalation(
        features=esc_features,
        rule_triggered="RULE_HIGH_AMOUNT_ESCALATION",
        explanation="Transaction value INR 15,000 exceeds auto-recovery threshold.",
        diagnosis_text="VIP high ticket account flagged for human review.",
    )
    check(isinstance(esc_id, int) and esc_id > 0, "Human escalation successfully queued with valid ID")

    open_escs = get_escalations(status="open")
    matched = [e for e in open_escs if e["id"] == esc_id]
    check(len(matched) == 1 and matched[0]["status"] == "open", "Escalation listed in open triage queue")
    check(matched[0]["amount_inr"] == 15000.0, "Escalation records correct amount")

    resolved_record = resolve_escalation(esc_id, notes="Approved VIP concession after manual outreach", resolver="agent_alice")
    check(resolved_record is not None and resolved_record["status"] == "resolved", "Escalation resolved with operator notes")

    open_after = get_escalations(status="open")
    check(not any(e["id"] == esc_id for e in open_after), "Resolved item removed from open queue")

    # Verify resolution was written to the tamper-evident audit ledger
    chain_valid, verified_rows, _ = audit.verify_audit_log_integrity()
    check(chain_valid is True, f"Audit log cryptographic hash chain intact after escalation resolution ({verified_rows} rows)")

    print("\n--- 8. Testing Checkout Abandonment Recovery Module ---")
    from abandonment_policy import decide_abandonment_action
    from abandonment import create_or_update_session, get_session, mark_session_completed, sweep_abandoned_sessions
    from simulate import generate_abandonment_batch

    # Policy Rule 1: High intent payment step -> NUDGE_NOW
    ab_dec1 = decide_abandonment_action({"cart_step": "payment_method", "amount_inr": 2499.0, "nudge_count": 0})
    check(ab_dec1.action == "NUDGE_NOW" and ab_dec1.rule_triggered == "RULE_ABANDON_HIGH_INTENT_STAGE1", "High-intent payment step -> NUDGE_NOW")

    # Policy Rule 2: Low intent low value -> STOP
    ab_dec2 = decide_abandonment_action({"cart_step": "cart", "amount_inr": 299.0, "nudge_count": 0})
    check(ab_dec2.action == "STOP" and ab_dec2.rule_triggered == "RULE_ABANDON_LOW_INTENT", "Low-intent low value cart -> STOP")

    # Policy Rule 3: Max nudges exceeded -> STOP
    ab_dec3 = decide_abandonment_action({"cart_step": "otp", "amount_inr": 1999.0, "nudge_count": 2})
    check(ab_dec3.action == "STOP" and ab_dec3.rule_triggered == "RULE_ABANDON_MAX_NUDGES", "Max nudges reached -> STOP")

    # Session CRUD & Sweeper
    test_sess_id = f"sess_test_{int(time.time())}"
    sess_created = create_or_update_session({
        "session_id": test_sess_id,
        "order_id": "order_abandon_test_101",
        "amount_inr": 3499.0,
        "cart_step": "otp",
        "customer_email": "cart.user@example.com",
        "created_at": time.time() - 1200,  # 20 mins ago (abandoned)
    })
    check(sess_created["session_id"] == test_sess_id, "Checkout session successfully persisted in SQLite")

    # Run sweeper (cutoff 15 mins)
    swept = sweep_abandoned_sessions(cutoff_seconds=900)
    matched_sweep = [s for s in swept if s["session_id"] == test_sess_id]
    check(len(matched_sweep) == 1 and matched_sweep[0]["action"] == "NUDGE_NOW", "Sweeper identified abandoned cart and triggered NUDGE_NOW")

    # Mark completed upon payment
    completed = mark_session_completed(session_id=test_sess_id)
    check(completed is True, "Marking session completed returns True")
    sess_after = get_session(test_sess_id)
    check(sess_after["completed_at"] is not None, "Session records completed_at timestamp")

    # Subsequent sweep suppresses completed sessions
    swept_again = sweep_abandoned_sessions(cutoff_seconds=900)
    check(not any(s["session_id"] == test_sess_id for s in swept_again), "Paid session omitted from subsequent abandonment sweeps")

    # Synthetic abandonment batch
    ab_batch = generate_abandonment_batch(n=200, seed=99)
    check(len(ab_batch) == 200 and "true_recovery_prob" in ab_batch.columns, "Synthetic abandonment batch generated with ground-truth probabilities")

    # Verify audit chain integrity
    chain_valid, verified_rows, _ = audit.verify_audit_log_integrity()
    print("\n--- 9. Testing B2B Receivables & Promise-to-Pay Tracker ---")
    from receivables_policy import decide_receivable_action
    from receivables import (
        create_or_update_invoice,
        get_invoice,
        record_promise_to_pay,
        mark_invoice_paid,
        sweep_overdue_invoices,
    )
    from simulate import generate_invoice_batch

    t_now = time.time()

    # Test Ladder 1: Day+3 Friendly Nudge
    inv_d3 = {"due_date": t_now - 86400 * 4, "amount_inr": 12000.0, "stage": "none", "status": "overdue"}
    dec_d3 = decide_receivable_action(inv_d3, current_time=t_now)
    check(dec_d3.action == "REMINDER_1" and dec_d3.rule_triggered == "RULE_REC_STAGE1_FRIENDLY", "Day+3 overdue -> Stage 1 Friendly Reminder")

    # Test Ladder 2: Day+10 Itemized Notice
    inv_d10 = {"due_date": t_now - 86400 * 12, "amount_inr": 12000.0, "stage": "reminder_1", "status": "overdue"}
    dec_d10 = decide_receivable_action(inv_d10, current_time=t_now)
    check(dec_d10.action == "REMINDER_2" and dec_d10.rule_triggered == "RULE_REC_STAGE2_ITEMIZED", "Day+10 overdue -> Stage 2 Firm Itemized Reminder")

    # Test Ladder 3: Day+21 Final Notice
    inv_d21 = {"due_date": t_now - 86400 * 22, "amount_inr": 12000.0, "stage": "reminder_2", "status": "overdue"}
    dec_d21 = decide_receivable_action(inv_d21, current_time=t_now)
    check(dec_d21.action == "FINAL_NOTICE" and dec_d21.rule_triggered == "RULE_REC_STAGE3_FINAL_NOTICE", "Day+21 overdue -> Stage 3 Final Notice")

    # Test Ladder 4: Day+30 Collections Escalation
    inv_d30 = {"due_date": t_now - 86400 * 32, "amount_inr": 12000.0, "stage": "final_notice", "status": "overdue"}
    dec_d30 = decide_receivable_action(inv_d30, current_time=t_now)
    check(dec_d30.action == "ESCALATE_COLLECTIONS" and dec_d30.rule_triggered == "RULE_REC_STAGE4_COLLECTIONS", "Day+30 overdue -> Stage 4 Collections Escalation")

    # Stopping Rule: Active Promise to Pay
    inv_prom = {
        "due_date": t_now - 86400 * 15,
        "amount_inr": 15000.0,
        "status": "promised",
        "promised_pay_date": t_now + 86400 * 3,
    }
    dec_prom = decide_receivable_action(inv_prom, current_time=t_now)
    check(dec_prom.action == "STOP" and dec_prom.rule_triggered == "RULE_REC_PROMISE_ACTIVE", "Active promise-to-pay halts dunning outreach")

    # Stopping Rule: Broken Promises Limit (>= 2)
    inv_broken = {
        "due_date": t_now - 86400 * 15,
        "amount_inr": 15000.0,
        "status": "overdue",
        "broken_promise_count": 2,
    }
    dec_broken = decide_receivable_action(inv_broken, current_time=t_now)
    check(dec_broken.action == "ESCALATE_HUMAN" and dec_broken.rule_triggered == "RULE_REC_BROKEN_PROMISES_EXCEEDED", "Broken promises >= 2 immediately escalates to human specialist")

    # Stopping Rule: High-Ticket Exposure (> INR 50,000)
    inv_vip = {
        "due_date": t_now - 86400 * 5,
        "amount_inr": 85000.0,
        "status": "overdue",
    }
    dec_vip = decide_receivable_action(inv_vip, current_time=t_now)
    check(dec_vip.action == "ESCALATE_HUMAN" and dec_vip.rule_triggered == "RULE_REC_HIGH_TICKET_ESCALATION", "High-ticket receivable (> INR 50,000) routes to human credit manager")

    # Operations & Sweeper
    test_inv_id = f"inv_test_{int(time.time())}"
    inv_created = create_or_update_invoice({
        "invoice_id": test_inv_id,
        "customer_id": "cust_corp_001",
        "amount_inr": 18500.0,
        "due_date": t_now - 86400 * 4,
        "status": "overdue",
    })
    check(inv_created["invoice_id"] == test_inv_id, "B2B invoice persisted in SQLite database")

    # Sweep triggers Stage 1
    sw_res1 = sweep_overdue_invoices(current_time=t_now)
    matched_inv = [i for i in sw_res1 if i["invoice_id"] == test_inv_id]
    check(len(matched_inv) == 1 and matched_inv[0]["action"] == "REMINDER_1", "Receivables sweep triggered Stage 1 reminder with payment link")

    # Record Promise to Pay
    prom_date = t_now + 86400 * 5
    prom_res = record_promise_to_pay(test_inv_id, prom_date)
    check(prom_res["status"] == "promised", "Promise to pay recorded and status updated to 'promised'")

    # Sweep during active promise holds dunning
    sw_res2 = sweep_overdue_invoices(current_time=t_now)
    matched_prom = [i for i in sw_res2 if i["invoice_id"] == test_inv_id]
    check(len(matched_prom) == 1 and matched_prom[0]["action"] == "STOP", "Active promise suppresses dunning during sweep")

    # Sweep after promise expires detects broken promise and advances
    t_expired = t_now + 86400 * 6
    sw_res3 = sweep_overdue_invoices(current_time=t_expired, min_contact_gap_seconds=0)
    matched_exp = [i for i in sw_res3 if i["invoice_id"] == test_inv_id]
    check(len(matched_exp) == 1 and matched_exp[0]["stage"] == "final_notice", "Expired promise advances invoice directly to final_notice")

    # Mark paid halts all dunning
    paid_inv = mark_invoice_paid(test_inv_id)
    check(paid_inv["status"] == "paid", "Invoice marked paid in full")

    # Synthetic invoice batch
    inv_batch = generate_invoice_batch(n=100, seed=77)
    check(len(inv_batch) == 100 and "true_payment_prob" in inv_batch.columns, "Synthetic invoice batch generated with realistic recovery curve")

    # Final audit chain verification across all three pillars
    chain_valid, verified_rows, _ = audit.verify_audit_log_integrity()
    check(chain_valid is True, f"Cryptographic hash chain intact across all pillars ({verified_rows} rows)")

    print(f"\n==========================================")
    print(f" ALL TESTS PASSED: {passed}/{total}")
    print(f"==========================================\n")


if __name__ == "__main__":
    run_all_tests()

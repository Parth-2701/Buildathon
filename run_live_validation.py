"""
run_live_validation.py - Comprehensive 18-Case Live Validation Suite.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent

Validates all 3 recovery pillars, stopping rules, and operational workflows
against real Razorpay Test Mode APIs and the SHA-256 tamper-evident audit ledger:
- Category 1: One-Off Payment Failures (TC-01 to TC-08)
- Category 2: Subscription & Mandate Retry Sequencing (TC-09 to TC-12)
- Category 3: Checkout Abandonment Recovery (TC-13 to TC-15)
- Category 4: B2B Receivables Dunning & Promise Tracking (TC-16 to TC-17)
- Category 5: Actionable Human Escalation & Triage (TC-18)
"""

import sys
import os
import hmac
import hashlib
import json
import time
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from app import app
from audit import verify_audit_log_integrity

load_dotenv()

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
client = TestClient(app)


def send_webhook(tc: dict) -> dict:
    """Helper to dispatch simulated Razorpay webhooks to the local test client."""
    now_ms = int(time.time() * 1000)
    event_id = f"evt_{now_ms}_{tc['case_id']}"

    payload = {
        "entity": "event",
        "account_id": "acc_live_test_001",
        "event": tc["event"],
        "contains": [tc["event"].split(".")[0]],
        "payload": {},
        "created_at": int(time.time()),
        "id": event_id,
    }

    if "subscription" in tc["event"]:
        payload["payload"]["subscription"] = {
            "entity": tc.get("subscription", {})
        }
        if "entity" in tc:
            payload["payload"]["payment"] = {
                "entity": tc["entity"]
            }
    elif "order" in tc["event"]:
        payload["payload"]["order"] = {
            "entity": tc.get("order", {})
        }
    else:
        payload["payload"]["payment"] = {
            "entity": tc["entity"]
        }

    raw_bytes = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    if WEBHOOK_SECRET:
        sig = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()
        headers["X-Razorpay-Signature"] = sig

    res = client.post("/webhook", content=raw_bytes, headers=headers)
    return res.json()


def run_live_validation():
    print("\n================================================================================")
    print(" EXECUTING COMPREHENSIVE LIVE VALIDATION SUITE (18 Distinct Cases)")
    print(" Across All 3 Revenue Leakage Pillars + Human Triage & Hash Chain")
    print(" Real Razorpay Test Mode API + Hash-Chained Audit Trail + LLM Diagnostics")
    print("================================================================================")

    results = []
    passed = 0
    t_now = time.time()

    # ----------------------------------------------------
    # Category 1: One-Off Payment Failures (TC-01 to TC-08)
    # ----------------------------------------------------
    c1_cases = [
        {
            "case_id": "TC-01",
            "category": "One-Off Payment",
            "event": "payment.failed",
            "description": "Transient UPI Timeout (INR 1,499.00)",
            "expected_action": "RETRY_LINK_NOW",
            "expected_rule": "RULE_HIGH_PROB_IMMEDIATE_RETRY",
            "entity": {
                "id": f"pay_live_tc01_upi_{int(time.time())}",
                "amount": 149900,
                "currency": "INR",
                "method": "upi",
                "error_code": "BAD_REQUEST_ERROR",
                "error_reason": "payment_timed_out",
                "email": "customer.upi@example.com",
            }
        },
        {
            "case_id": "TC-02",
            "category": "One-Off Payment",
            "event": "payment.failed",
            "description": "Card Gateway Technical Error (INR 2,999.00)",
            "expected_action": "RETRY_LINK_NOW",
            "expected_rule": "RULE_HIGH_PROB_IMMEDIATE_RETRY",
            "entity": {
                "id": f"pay_live_tc02_card_{int(time.time())}",
                "amount": 299900,
                "currency": "INR",
                "method": "card",
                "error_code": "GATEWAY_ERROR",
                "error_reason": "gateway_technical_error",
                "email": "customer.card@example.com",
            }
        },
        {
            "case_id": "TC-03",
            "category": "One-Off Payment",
            "event": "payment.failed",
            "description": "Soft Failure - Insufficient Funds (INR 799.00)",
            "expected_action": "RETRY_LINK_DELAYED",
            "expected_rule": "RULE_LOW_PROB_DELAYED_NUDGE",
            "entity": {
                "id": f"pay_live_tc03_insufficient_{int(time.time())}",
                "amount": 79900,
                "currency": "INR",
                "method": "upi",
                "error_code": "BAD_REQUEST_ERROR",
                "error_reason": "insufficient_funds",
                "email": "customer.funds@example.com",
            }
        },
        {
            "case_id": "TC-04",
            "category": "One-Off Payment",
            "event": "payment.failed",
            "description": "Expired Card Instrument (INR 1,200.00)",
            "expected_action": "ESCALATE_HUMAN",
            "expected_rule": "RULE_HARD_DECLINE_COMPLIANCE",
            "entity": {
                "id": f"pay_live_tc04_expired_{int(time.time())}",
                "amount": 120000,
                "currency": "INR",
                "method": "card",
                "error_code": "BAD_REQUEST_ERROR",
                "error_reason": "card_expired",
                "email": "customer.expired@example.com",
            }
        },
        {
            "case_id": "TC-05",
            "category": "One-Off Payment",
            "event": "payment.failed",
            "description": "Compliance Hard Decline - Stolen Card (INR 3,500.00)",
            "expected_action": "ESCALATE_HUMAN",
            "expected_rule": "RULE_HARD_DECLINE_COMPLIANCE",
            "entity": {
                "id": f"pay_live_tc05_stolen_{int(time.time())}",
                "amount": 350000,
                "currency": "INR",
                "method": "card",
                "error_code": "BAD_REQUEST_ERROR",
                "error_reason": "stolen_card",
                "email": "customer.stolen@example.com",
            }
        },
        {
            "case_id": "TC-06",
            "category": "One-Off Payment",
            "event": "payment.failed",
            "description": "Compliance Hard Decline - Fraud Suspected (INR 4,200.00)",
            "expected_action": "ESCALATE_HUMAN",
            "expected_rule": "RULE_HARD_DECLINE_COMPLIANCE",
            "entity": {
                "id": f"pay_live_tc06_fraud_{int(time.time())}",
                "amount": 420000,
                "currency": "INR",
                "method": "card",
                "error_code": "BAD_REQUEST_ERROR",
                "error_reason": "fraud_suspected",
                "email": "fraud.test@example.com",
            }
        },
        {
            "case_id": "TC-07",
            "category": "One-Off Payment",
            "event": "payment.failed",
            "description": "High Value Risk Ceiling (> INR 10,000) (INR 28,500.00)",
            "expected_action": "ESCALATE_HUMAN",
            "expected_rule": "RULE_HIGH_AMOUNT_ESCALATION",
            "entity": {
                "id": f"pay_live_tc07_highval_{int(time.time())}",
                "amount": 2850000,
                "currency": "INR",
                "method": "card",
                "error_code": "BAD_REQUEST_ERROR",
                "error_reason": "payment_timed_out",
                "email": "vip.client@example.com",
            }
        },
        {
            "case_id": "TC-08",
            "category": "One-Off Payment",
            "event": "payment.failed",
            "description": "Stopping Rule - Active Cooldown Suppression",
            "expected_action": "STOP",
            "expected_rule": "RULE_COOLDOWN_ACTIVE",
            "is_cooldown_pair": True,
            "entity": {
                "id": f"pay_live_tc08_cooldown_{int(time.time())}",
                "amount": 150000,
                "currency": "INR",
                "method": "upi",
                "error_code": "BAD_REQUEST_ERROR",
                "error_reason": "payment_timed_out",
                "email": "cooldown.user@example.com",
            }
        },
    ]

    for tc in c1_cases:
        print(f"\n[{tc['case_id']}] ({tc['category']}) {tc['description']}")
        print(f"       Expected: {tc['expected_action']} via {tc['expected_rule']}")
        try:
            if tc.get("is_cooldown_pair"):
                send_webhook(tc)
                time.sleep(0.2)
                res = send_webhook(tc)
            else:
                res = send_webhook(tc)

            actual_act = res.get("decision")
            actual_rule = res.get("rule")
            is_match = (actual_act == tc["expected_action"]) and (actual_rule == tc["expected_rule"])
            if is_match:
                passed += 1
                print(f"       Result  : [PASS] -> Action: {actual_act} | Rule: {actual_rule}")
                if res.get("payment_link"):
                    print(f"       Razorpay Link Generated: {res.get('payment_link')}")
                if res.get("diagnosis"):
                    print(f"       LLM Diagnosis: \"{res.get('diagnosis')}\"")
            else:
                print(f"       Result  : [FAIL] -> Action: {actual_act} | Rule: {actual_rule}")
        except Exception as e:
            print(f"       [ERROR] {e}")

    # ----------------------------------------------------
    # Category 2: Subscription Mandate Sequencing (TC-09 to TC-12)
    # ----------------------------------------------------
    c2_cases = [
        {
            "case_id": "TC-09",
            "category": "Subscription Mandate",
            "event": "subscription.charged.failed",
            "description": "Subscription 1st Mandate Failure - Transient (INR 999/mo)",
            "expected_action": "SCHEDULE_RETRY_DAY_1",
            "expected_rule": "RULE_SUB_STAGE_1_RETRY",
            "subscription": {
                "id": f"sub_live_tc09_{int(time.time())}",
                "plan_id": "plan_starter_monthly",
                "current_cycle": 1,
            },
            "entity": {
                "id": f"pay_sub_tc09_{int(time.time())}",
                "amount": 99900,
                "error_reason": "payment_timed_out",
                "method": "card",
            }
        },
        {
            "case_id": "TC-10",
            "category": "Subscription Mandate",
            "event": "subscription.charged.failed",
            "description": "Subscription 2nd Mandate Failure - Insufficient Funds (INR 1,499/mo)",
            "expected_action": "SCHEDULE_RETRY_DAY_3",
            "expected_rule": "RULE_SUB_STAGE_2_LIQUIDITY_BUFFER",
            "prior_failures_setup": 1,
            "subscription": {
                "id": f"sub_live_tc10_{int(time.time())}",
                "plan_id": "plan_pro_monthly",
                "current_cycle": 2,
            },
            "entity": {
                "id": f"pay_sub_tc10_{int(time.time())}",
                "amount": 149900,
                "error_reason": "insufficient_funds",
                "method": "card",
            }
        },
        {
            "case_id": "TC-11",
            "category": "Subscription Mandate",
            "event": "subscription.charged.failed",
            "description": "Subscription Expired Mandate Card -> Update Payment Method Link",
            "expected_action": "SEND_UPDATE_PAYMENT_METHOD_LINK",
            "expected_rule": "RULE_SUB_INSTRUMENT_UPDATE_REQUIRED",
            "subscription": {
                "id": f"sub_live_tc11_{int(time.time())}",
                "plan_id": "plan_biz_monthly",
                "current_cycle": 3,
            },
            "entity": {
                "id": f"pay_sub_tc11_{int(time.time())}",
                "amount": 199900,
                "error_reason": "card_expired",
                "method": "card",
            }
        },
        {
            "case_id": "TC-12",
            "category": "Subscription Mandate",
            "event": "subscription.charged.failed",
            "description": "Subscription 3+ Mandate Failures -> Cancel/Stop to Prevent Fines",
            "expected_action": "CANCEL_SUBSCRIPTION_STOP",
            "expected_rule": "RULE_SUB_MAX_RETRIES_EXCEEDED",
            "prior_failures_setup": 3,
            "subscription": {
                "id": f"sub_live_tc12_{int(time.time())}",
                "plan_id": "plan_corp_monthly",
                "current_cycle": 4,
            },
            "entity": {
                "id": f"pay_sub_tc12_{int(time.time())}",
                "amount": 99900,
                "error_reason": "insufficient_funds",
                "method": "card",
            }
        },
    ]

    for tc in c2_cases:
        print(f"\n[{tc['case_id']}] ({tc['category']}) {tc['description']}")
        print(f"       Expected: {tc['expected_action']} via {tc['expected_rule']}")
        try:
            if tc.get("prior_failures_setup"):
                from features import global_tracker
                key = tc.get("subscription", {}).get("id") or tc["entity"]["id"]
                for _ in range(tc["prior_failures_setup"]):
                    global_tracker.record_failure(key)

            res = send_webhook(tc)
            actual_act = res.get("decision")
            actual_rule = res.get("rule")
            is_match = (actual_act == tc["expected_action"]) and (actual_rule == tc["expected_rule"])
            if is_match:
                passed += 1
                print(f"       Result  : [PASS] -> Action: {actual_act} | Rule: {actual_rule}")
                if res.get("payment_link"):
                    print(f"       Razorpay Link Generated: {res.get('payment_link')}")
                if res.get("diagnosis"):
                    print(f"       LLM Diagnosis: \"{res.get('diagnosis')}\"")
            else:
                print(f"       Result  : [FAIL] -> Action: {actual_act} | Rule: {actual_rule}")
        except Exception as e:
            print(f"       [ERROR] {e}")

    # ----------------------------------------------------
    # Category 3: Checkout Abandonment Recovery (TC-13 to TC-15)
    # ----------------------------------------------------
    # TC-13: High-Intent Drop-off (OTP step) -> NUDGE_NOW
    print(f"\n[TC-13] (Checkout Abandonment) High-Intent Cart Abandonment at OTP Friction (INR 3,499.00)")
    print("       Expected: NUDGE_NOW via RULE_ABANDON_HIGH_INTENT_STAGE1")
    s13_id = f"sess_live_tc13_{int(time.time())}"
    client.post("/checkout/session", json={
        "session_id": s13_id,
        "order_id": f"order_live_tc13_{int(time.time())}",
        "amount_inr": 3499.0,
        "cart_step": "otp",
        "customer_email": "shopper.tc13@example.com",
        "created_at": time.time() - 1200,
    })
    sw13 = client.post("/checkout/sweep?cutoff_seconds=900").json()
    match13 = [s for s in sw13.get("results", []) if s["session_id"] == s13_id]
    if match13 and match13[0]["action"] == "NUDGE_NOW" and match13[0]["rule"] == "RULE_ABANDON_HIGH_INTENT_STAGE1":
        passed += 1
        print(f"       Result  : [PASS] -> Action: {match13[0]['action']} | Rule: {match13[0]['rule']}")
        if match13[0].get("payment_link"):
            print(f"       Razorpay Link Generated: {match13[0]['payment_link']}")
    else:
        print(f"       Result  : [FAIL] -> {match13}")

    # TC-14: Low-Intent Window Shopping (< INR 500 cart) -> STOP
    print(f"\n[TC-14] (Checkout Abandonment) Low-Intent Window-Shopping Suppression (< INR 500)")
    print("       Expected: STOP via RULE_ABANDON_LOW_INTENT")
    s14_id = f"sess_live_tc14_{int(time.time())}"
    client.post("/checkout/session", json={
        "session_id": s14_id,
        "order_id": f"order_live_tc14_{int(time.time())}",
        "amount_inr": 299.0,
        "cart_step": "cart",
        "customer_email": "shopper.tc14@example.com",
        "created_at": time.time() - 1200,
    })
    sw14 = client.post("/checkout/sweep?cutoff_seconds=900").json()
    match14 = [s for s in sw14.get("results", []) if s["session_id"] == s14_id]
    if match14 and match14[0]["action"] == "STOP" and match14[0]["rule"] == "RULE_ABANDON_LOW_INTENT":
        passed += 1
        print(f"       Result  : [PASS] -> Action: {match14[0]['action']} | Rule: {match14[0]['rule']} (Spam suppressed)")
    else:
        print(f"       Result  : [FAIL] -> {match14}")

    # TC-15: Order Paid Webhook clears session -> STOP
    print(f"\n[TC-15] (Checkout Abandonment) Order Paid Webhook Clears Abandoned Session")
    print("       Expected: Session marked completed; subsequent sweep omits session")
    s15_id = f"sess_live_tc15_{int(time.time())}"
    o15_id = f"order_live_tc15_{int(time.time())}"
    client.post("/checkout/session", json={
        "session_id": s15_id,
        "order_id": o15_id,
        "amount_inr": 4500.0,
        "cart_step": "payment_method",
        "created_at": time.time() - 1200,
    })
    # Simulate Razorpay order.paid event
    send_webhook({
        "case_id": "TC-15",
        "event": "order.paid",
        "order": {"id": o15_id, "amount": 450000},
        "entity": {"id": f"pay_tc15_{int(time.time())}", "order_id": o15_id, "amount": 450000}
    })
    sw15 = client.post("/checkout/sweep?cutoff_seconds=900").json()
    match15 = [s for s in sw15.get("results", []) if s["session_id"] == s15_id]
    if len(match15) == 0:
        passed += 1
        print(f"       Result  : [PASS] -> Session {s15_id} successfully marked completed and suppressed from outreach")
    else:
        print(f"       Result  : [FAIL] -> Session still swept: {match15}")

    # ----------------------------------------------------
    # Category 4: B2B Receivables Dunning (TC-16 to TC-17)
    # ----------------------------------------------------
    # TC-16: Overdue B2B Invoice Day+3 -> REMINDER_1
    print(f"\n[TC-16] (B2B Receivables) Overdue Invoice Day+3 Friendly Nudge (INR 18,500.00)")
    print("       Expected: REMINDER_1 via RULE_REC_STAGE1_FRIENDLY")
    inv16_id = f"inv_live_tc16_{int(time.time())}"
    client.post("/invoices", json={
        "invoice_id": inv16_id,
        "customer_id": "cust_corp_tc16",
        "amount_inr": 18500.0,
        "due_date": time.time() - 86400 * 4,
        "status": "overdue",
    })
    sw16 = client.post("/invoices/sweep").json()
    match16 = [i for i in sw16.get("results", []) if i["invoice_id"] == inv16_id]
    if match16 and match16[0]["action"] == "REMINDER_1" and match16[0]["rule"] == "RULE_REC_STAGE1_FRIENDLY":
        passed += 1
        print(f"       Result  : [PASS] -> Action: {match16[0]['action']} | Rule: {match16[0]['rule']}")
        if match16[0].get("payment_link"):
            print(f"       Razorpay Link Generated: {match16[0]['payment_link']}")
    else:
        print(f"       Result  : [FAIL] -> {match16}")

    # TC-17: Active Promise to Pay pauses dunning -> STOP
    print(f"\n[TC-17] (B2B Receivables) Promise-to-Pay Active Hold")
    print("       Expected: STOP via RULE_REC_PROMISE_ACTIVE")
    client.post(f"/invoices/{inv16_id}/promise", json={
        "promised_date": time.time() + 86400 * 7
    })
    sw17 = client.post("/invoices/sweep").json()
    match17 = [i for i in sw17.get("results", []) if i["invoice_id"] == inv16_id]
    if match17 and match17[0]["action"] == "STOP" and match17[0]["rule"] == "RULE_REC_PROMISE_ACTIVE":
        passed += 1
        print(f"       Result  : [PASS] -> Action: {match17[0]['action']} | Rule: {match17[0]['rule']} (Dunning paused)")
    else:
        print(f"       Result  : [FAIL] -> {match17}")

    # ----------------------------------------------------
    # Category 5: Actionable Human Escalation Triage (TC-18)
    # ----------------------------------------------------
    print(f"\n[TC-18] (Human Escalation Triage) Operator Resolves Queued Ticket with Audit Chain")
    print("       Expected: Status transitioned to 'resolved' and ledger entry chained")
    escs = client.get("/escalations?status=open").json().get("escalations", [])
    if escs:
        target_esc = escs[0]
        esc_id = target_esc["id"]
        res_esc = client.post(f"/escalations/{esc_id}/resolve", json={
            "notes": "Verified VIP account manually; extended credit terms.",
            "resolver": "concierge_lead",
        }).json()
        if res_esc.get("status") == "resolved" and res_esc.get("escalation", {}).get("status") == "resolved":
            passed += 1
            print(f"       Result  : [PASS] -> Escalation #{esc_id} resolved by concierge_lead with audit log")
        else:
            print(f"       Result  : [FAIL] -> {res_esc}")
    else:
        print("       Result  : [SKIP] No open escalations to resolve")

    print("\n================================================================================")
    print(f" LIVE VALIDATION SUMMARY: {passed}/18 Cases Verified Compliant & Correct")

    is_valid, count, err = verify_audit_log_integrity()
    if is_valid:
        print(f" Cryptographic Hash Chain: VERIFIED INTACT ({count} tamper-evident rows)")
    else:
        print(f" [WARNING] Hash Chain Alert: {err}")
    print("================================================================================\n")


if __name__ == "__main__":
    run_live_validation()

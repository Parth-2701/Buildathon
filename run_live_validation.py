"""
run_live_validation.py - Executes live Test Mode validation across 12 distinct failure cases.
Covers One-Off Payments & Subscription Mandates with real Razorpay Test Mode API & Hash-Chained Audit Logging.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent
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

SERVER_URL = os.getenv("WEBHOOK_TARGET_URL", "http://localhost:5000/webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

TEST_CASES = [
    # ----------------------------------------------------
    # Category 1: One-Off Payment Failures (TC-01 to TC-08)
    # ----------------------------------------------------
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
            "error_description": "UPI gateway session timed out",
            "email": "customer.upi@example.com",
            "contact": "+919876543210",
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
            "error_description": "Bank switch connection dropped",
            "email": "customer.card@example.com",
            "contact": "+919876543210",
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
            "id": f"pay_live_tc03_lowfunds_{int(time.time())}",
            "amount": 79900,
            "currency": "INR",
            "method": "upi",
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "insufficient_funds",
            "error_description": "Account balance insufficient",
            "email": "user.lowfunds@example.com",
            "contact": "+919876543210",
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
            "error_description": "Card expiry date in the past",
            "email": "user.expired@example.com",
            "contact": "+919876543210",
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
            "error_description": "Card reported stolen to issuing bank",
            "email": "fraud.test@example.com",
            "contact": "+919876543210",
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
            "error_description": "Internal risk filter score exceeded",
            "email": "suspicious@example.com",
            "contact": "+919876543210",
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
            "error_reason": "gateway_technical_error",
            "error_description": "Timeout on large enterprise order",
            "email": "enterprise.buyer@example.com",
            "contact": "+919876543210",
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
            "amount": 180000,
            "currency": "INR",
            "method": "card",
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "gateway_technical_error",
            "error_description": "Repeated immediate failure",
            "email": "customer.cooldown@example.com",
            "contact": "+919876543210",
        }
    },

    # ----------------------------------------------------
    # Category 2: Subscription & Mandate Recoveries (TC-09 to TC-12)
    # ----------------------------------------------------
    {
        "case_id": "TC-09",
        "category": "Subscription Mandate",
        "event": "subscription.charged.failed",
        "description": "Subscription 1st Mandate Failure - Transient (INR 999/mo)",
        "expected_action": "SCHEDULE_RETRY_DAY_1",
        "expected_rule": "RULE_SUB_STAGE_1_RETRY",
        "entity": {
            "id": f"pay_live_tc09_sub_{int(time.time())}",
            "amount": 99900,
            "currency": "INR",
            "method": "card",
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "payment_timed_out",
            "error_description": "Mandate charge timed out on bank switch",
            "email": "sub.user1@example.com",
            "contact": "+919876543210",
        },
        "subscription": {
            "id": f"sub_live_001_{int(time.time())}",
            "plan_id": "plan_monthly_pro",
        }
    },
    {
        "case_id": "TC-10",
        "category": "Subscription Mandate",
        "event": "subscription.charged.failed",
        "description": "Subscription 2nd Mandate Failure - Insufficient Funds (INR 1,499/mo)",
        "expected_action": "SCHEDULE_RETRY_DAY_3",
        "expected_rule": "RULE_SUB_STAGE_2_LIQUIDITY_BUFFER",
        "entity": {
            "id": f"pay_live_tc10_sub_{int(time.time())}",
            "amount": 149900,
            "currency": "INR",
            "method": "upi",
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "insufficient_funds",
            "error_description": "Mandate auto-debit balance unavailable",
            "email": "sub.user2@example.com",
            "contact": "+919876543210",
        },
        "subscription": {
            "id": f"sub_live_002_{int(time.time())}",
            "plan_id": "plan_annual_growth",
        },
        "prior_failures_setup": 1,
    },
    {
        "case_id": "TC-11",
        "category": "Subscription Mandate",
        "event": "subscription.charged.failed",
        "description": "Subscription Expired Mandate Card -> Update Payment Method Link",
        "expected_action": "SEND_UPDATE_PAYMENT_METHOD_LINK",
        "expected_rule": "RULE_SUB_INSTRUMENT_UPDATE_REQUIRED",
        "entity": {
            "id": f"pay_live_tc11_sub_{int(time.time())}",
            "amount": 199900,
            "currency": "INR",
            "method": "card",
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "card_expired",
            "error_description": "Mandate token card expired",
            "email": "sub.expired@example.com",
            "contact": "+919876543210",
        },
        "subscription": {
            "id": f"sub_live_003_{int(time.time())}",
            "plan_id": "plan_premium_tier",
        }
    },
    {
        "case_id": "TC-12",
        "category": "Subscription Mandate",
        "event": "subscription.charged.failed",
        "description": "Subscription 3+ Mandate Failures -> Cancel/Stop to Prevent Fines",
        "expected_action": "CANCEL_SUBSCRIPTION_STOP",
        "expected_rule": "RULE_SUB_MAX_RETRIES_EXCEEDED",
        "entity": {
            "id": f"pay_live_tc12_sub_{int(time.time())}",
            "amount": 99900,
            "currency": "INR",
            "method": "card",
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "insufficient_funds",
            "error_description": "Repeated 4th failed debit attempt",
            "email": "sub.churn@example.com",
            "contact": "+919876543210",
        },
        "subscription": {
            "id": f"sub_live_004_{int(time.time())}",
            "plan_id": "plan_starter",
        },
        "prior_failures_setup": 3,
    },
]

client = TestClient(app)


def send_webhook(tc: dict) -> dict:
    payload = {
        "id": f"evt_{int(time.time()*1000)}_{tc['case_id']}",
        "entity": "event",
        "account_id": "acc_live_validator",
        "event": tc.get("event", "payment.failed"),
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": tc["entity"]
            }
        },
    }

    if "subscription" in tc:
        payload["payload"]["subscription"] = {"entity": tc["subscription"]}

    raw_bytes = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    if WEBHOOK_SECRET:
        sig = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()
        headers["X-Razorpay-Signature"] = sig

    res = client.post("/webhook", content=raw_bytes, headers=headers)
    return res.json()


def run_live_validation():
    print("\n================================================================================")
    print(" EXECUTING LIVE TEST MODE VALIDATION (12 Distinct Cases)")
    print(" Covers: One-Off Payment Failures & Subscription Mandate Retry Sequencing")
    print(" Real Razorpay Test Mode API + Hash-Chained Audit Trail + LLM Diagnostics")
    print("================================================================================")

    results = []
    passed = 0

    for tc in TEST_CASES:
        case_id = tc["case_id"]
        category = tc["category"]
        desc = tc["description"]
        expected_act = tc["expected_action"]
        expected_rule = tc["expected_rule"]

        print(f"\n[{case_id}] ({category}) {desc}")
        print(f"       Expected: {expected_act} via {expected_rule}")

        try:
            # Handle prior failure setups for testing multi-step lifecycle
            if tc.get("prior_failures_setup"):
                from features import global_tracker
                key = tc.get("subscription", {}).get("id") or tc["entity"]["id"]
                for _ in range(tc["prior_failures_setup"]):
                    global_tracker.record_failure(key)

            if tc.get("is_cooldown_pair"):
                res1 = send_webhook(tc)
                time.sleep(0.5)
                res = send_webhook(tc)
            else:
                res = send_webhook(tc)

            actual_act = res.get("decision")
            actual_rule = res.get("rule")
            link_url = res.get("payment_link")
            diag = res.get("diagnosis")

            is_match = (actual_act == expected_act) and (actual_rule == expected_rule)
            if is_match:
                passed += 1
                status_str = "[PASS]"
            else:
                status_str = "[FAIL]"

            print(f"       Result  : {status_str} -> Action: {actual_act} | Rule: {actual_rule}")
            if link_url:
                print(f"       Razorpay Link Generated: {link_url}")
            if diag:
                print(f"       LLM Diagnosis: \"{diag}\"")

            results.append({
                "case_id": case_id,
                "category": category,
                "description": desc,
                "expected_action": expected_act,
                "actual_action": actual_act,
                "rule_triggered": actual_rule,
                "payment_link": link_url or "N/A (Scheduled / Escalated / Suppressed)",
                "passed": is_match,
            })

            time.sleep(0.5)

        except Exception as e:
            print(f"       [ERROR] Exception: {e}")

    print("\n================================================================================")
    print(f" LIVE VALIDATION SUMMARY: {passed}/{len(TEST_CASES)} Cases Verified Compliant & Correct")
    
    # Audit log verification
    is_valid, count, err = verify_audit_log_integrity()
    if is_valid:
        print(f" Cryptographic Hash Chain: VERIFIED INTACT ({count} tamper-evident rows)")
    else:
        print(f" [WARNING] Hash Chain Alert: {err}")
    print("================================================================================\n")


if __name__ == "__main__":
    run_live_validation()

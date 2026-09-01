"""
send_test_webhook.py - Interactive CLI tool to manually send test webhooks to http://localhost:5000/webhook
"""

import sys
import os
import hmac
import hashlib
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()

SERVER_URL = os.getenv("WEBHOOK_TARGET_URL", "http://localhost:5000/webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")


def send_payload(entity: dict) -> dict:
    payload = {
        "entity": "event",
        "account_id": "acc_manual_tester",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": entity
            }
        },
    }

    raw_bytes = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    if WEBHOOK_SECRET:
        signature = hmac.new(
            WEBHOOK_SECRET.encode("utf-8"), raw_bytes, hashlib.sha256
        ).hexdigest()
        headers["X-Razorpay-Signature"] = signature

    # 30-second timeout to allow for external Razorpay Test API round-trips
    response = requests.post(SERVER_URL, data=raw_bytes, headers=headers, timeout=30)
    return response.json()


def run_scenario(choice: str):
    ts = int(time.time())

    try:
        if choice == "1":
            print("\n========================================================")
            print(">> Scenario 1: Transient Error -> Immediate Payment Link")
            print("   Expected: RETRY_LINK_NOW (Creates Razorpay Payment Link)")
            print("========================================================")
            res = send_payload({
                "id": f"pay_transient_{ts}",
                "amount": 450000,  # INR 4,500
                "currency": "INR",
                "method": "card",
                "error_code": "BAD_REQUEST_ERROR",
                "error_reason": "gateway_technical_error",
                "error_description": "Bank gateway connection timeout",
                "email": "customer1@example.com",
                "contact": "+919876543210",
            })
            print(f"   Agent Action : {res.get('decision')}")
            print(f"   Rule Fired   : {res.get('rule')}")
            print(f"   Payment Link : {res.get('payment_link')}")

        elif choice == "2":
            print("\n========================================================")
            print(">> Scenario 2: Hard Decline (Stolen Card) -> Compliant Escalation")
            print("   Expected: ESCALATE_HUMAN (Strict compliance; zero auto retries)")
            print("========================================================")
            res = send_payload({
                "id": f"pay_stolen_{ts}",
                "amount": 120000,  # INR 1,200
                "currency": "INR",
                "method": "card",
                "error_code": "BAD_REQUEST_ERROR",
                "error_reason": "stolen_card",
                "error_description": "Card reported stolen by issuing bank",
                "email": "fraud.alert@example.com",
                "contact": "+919876543210",
            })
            print(f"   Agent Action : {res.get('decision')}")
            print(f"   Rule Fired   : {res.get('rule')}")

        elif choice == "3":
            print("\n========================================================")
            print(">> Scenario 3: High Ticket Amount (> INR 10,000) -> Human Review")
            print("   Expected: ESCALATE_HUMAN (Amount ceiling rule)")
            print("========================================================")
            res = send_payload({
                "id": f"pay_highval_{ts}",
                "amount": 2500000,  # INR 25,000
                "currency": "INR",
                "method": "card",
                "error_code": "BAD_REQUEST_ERROR",
                "error_reason": "payment_timed_out",
                "error_description": "Timed out waiting for OTP",
                "email": "vip.buyer@example.com",
                "contact": "+919876543210",
            })
            print(f"   Agent Action : {res.get('decision')}")
            print(f"   Rule Fired   : {res.get('rule')}")

        elif choice == "4":
            print("\n========================================================")
            print(">> Scenario 4: Soft Failure (Insufficient Funds) -> Delayed Retry")
            print("   Expected: RETRY_LINK_DELAYED (Probability 35% < 40%)")
            print("========================================================")
            res = send_payload({
                "id": f"pay_lowfunds_{ts}",
                "amount": 99900,  # INR 999
                "currency": "INR",
                "method": "upi",
                "error_code": "BAD_REQUEST_ERROR",
                "error_reason": "insufficient_funds",
                "error_description": "Customer balance low",
                "email": "user4@example.com",
                "contact": "+919876543210",
            })
            print(f"   Agent Action : {res.get('decision')}")
            print(f"   Rule Fired   : {res.get('rule')}")

        elif choice == "5":
            print("\n========================================================")
            print(">> Scenario 5: Duplicate Action within Cooldown Window")
            print("   Demonstrates stopping rule when multiple webhooks fire for same txn")
            print("========================================================")
            test_id = f"pay_cooldown_test_{ts}"
            payload = {
                "id": test_id,
                "amount": 350000,
                "currency": "INR",
                "method": "card",
                "error_code": "BAD_REQUEST_ERROR",
                "error_reason": "gateway_technical_error",
                "email": "customer.cooldown@example.com",
                "contact": "+919876543210",
            }
            print(f"   [Step 1] Sending initial failure for {test_id}...")
            res1 = send_payload(payload)
            print(f"            Agent Action : {res1.get('decision')}")
            print(f"            Rule Fired   : {res1.get('rule')}")

            print(f"\n   [Step 2] Sending immediate duplicate failure for SAME txn {test_id}...")
            res2 = send_payload(payload)
            print(f"            Agent Action : {res2.get('decision')}")
            print(f"            Rule Fired   : {res2.get('rule')}")
            if res2.get("decision") == "STOP":
                print("   -> SUCCESS: Cooldown stopping rule successfully suppressed duplicate outreach!")

    except requests.exceptions.Timeout:
        print(f"   [ERROR] Request timed out. Razorpay API call took longer than expected.")
    except requests.exceptions.ConnectionError:
        print(f"   [ERROR] Could not connect to {SERVER_URL}. Is Uvicorn running?")
    except Exception as e:
        print(f"   [ERROR] Unexpected exception: {e}")


def main():
    if len(sys.argv) > 1:
        choice = sys.argv[1].strip().lower()
    else:
        print("\nSelect a test webhook scenario:")
        print("  [1] Transient Error (Timeout)                -> RETRY_LINK_NOW")
        print("  [2] Hard Decline (Stolen Card)               -> ESCALATE_HUMAN")
        print("  [3] High Ticket Amount (> INR 10,000)        -> ESCALATE_HUMAN")
        print("  [4] Soft Failure (Insufficient Funds)        -> RETRY_LINK_DELAYED")
        print("  [5] 2-Step Cooldown Test (Duplicate failure) -> STOP")
        print("  [a] Run all scenarios")
        choice = input("\nEnter choice (1-5 or a): ").strip().lower()

    if choice == "a":
        for k in ["1", "2", "3", "4", "5"]:
            run_scenario(k)
            time.sleep(1)
    elif choice in ["1", "2", "3", "4", "5"]:
        run_scenario(choice)
    else:
        print(f"Invalid choice '{choice}'.")


if __name__ == "__main__":
    main()

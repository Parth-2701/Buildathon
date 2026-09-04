"""
test_manual.py - Interactive Manual Tester for Live Uvicorn Server.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent

Runs individual manual test steps against http://localhost:5000 with clean,
error-free HTTP payloads without PowerShell quoting or line-wrapping issues.
"""

import sys
import time
import json
import urllib.request
import urllib.error

BASE_URL = "http://localhost:5000"


def post_json(endpoint: str, data: dict = None) -> dict:
    url = f"{BASE_URL}{endpoint}"
    payload = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        print(f"[HTTP {e.code} Error] {err_msg}")
        return {"error": err_msg, "status_code": e.code}
    except Exception as e:
        print(f"[Connection Error] Could not connect to {url}: {e}")
        return {"error": str(e)}


def get_json(endpoint: str) -> dict:
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        print(f"[HTTP {e.code} Error] {err_msg}")
        return {"error": err_msg, "status_code": e.code}
    except Exception as e:
        print(f"[Connection Error] Could not connect to {url}: {e}")
        return {"error": str(e)}


def run_checkout_test():
    print("\n--- Testing Pillar 2: Checkout Cart Abandonment ---")
    cart_id = f"cart_manual_{int(time.time())}"
    print(f"1. Registering cart session: {cart_id} at OTP friction...")
    sess = post_json("/checkout/session", {
        "session_id": cart_id,
        "amount_inr": 2499.0,
        "cart_step": "otp",
        "customer_email": "shopper@example.com",
        "created_at": time.time() - 1200,
    })
    print("   Result:", json.dumps(sess, indent=2))

    print("\n2. Triggering cart sweeper...")
    sweep = post_json("/checkout/sweep?cutoff_seconds=60")
    print("   Result:", json.dumps(sweep, indent=2))


def run_receivables_test():
    print("\n--- Testing Pillar 3: B2B Receivables & Promise-to-Pay ---")
    inv_id = f"inv_manual_{int(time.time())}"
    print(f"1. Creating overdue B2B invoice: {inv_id}...")
    inv = post_json("/invoices", {
        "invoice_id": inv_id,
        "customer_id": "cust_acme_corp",
        "amount_inr": 18000.0,
        "due_date": time.time() - 86400 * 4,
        "status": "overdue",
    })
    print("   Result:", json.dumps(inv, indent=2))

    print(f"\n2. Registering Promise-to-Pay for {inv_id}...")
    prom = post_json(f"/invoices/{inv_id}/promise", {
        "promised_date": time.time() + 86400 * 7
    })
    print("   Result:", json.dumps(prom, indent=2))

    print("\n3. Triggering receivables sweeper (expecting dunning pause)...")
    sw = post_json("/invoices/sweep")
    print("   Result:", json.dumps(sw, indent=2))


def run_payment_test():
    print("\n--- Testing Pillar 1: Payment Failure Webhook ---")
    txn_id = f"pay_test_{int(time.time())}"
    print(f"1. Sending payment.failed webhook for {txn_id}...")
    res = post_json("/webhook", {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": txn_id,
                    "amount": 199900,
                    "currency": "INR",
                    "method": "upi",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_reason": "payment_timed_out",
                    "email": "buyer@example.com"
                }
            }
        }
    })
    print("   Result:", json.dumps(res, indent=2))


def run_escalation_test():
    print("\n--- Testing Actionable Human Escalation Triage ---")
    txn_id = f"pay_vip_{int(time.time())}"
    print(f"1. Triggering high-value payment failure (> INR 10,000): {txn_id}...")
    res = post_json("/webhook", {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": txn_id,
                    "amount": 2500000,
                    "currency": "INR",
                    "method": "card",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_reason": "payment_timed_out",
                    "email": "vip@example.com"
                }
            }
        }
    })
    print("   Result:", json.dumps(res, indent=2))

    print("\n2. Fetching open escalations queue...")
    escs = get_json("/escalations?status=open")
    items = escs.get("escalations", [])
    print(f"   Found {len(items)} open ticket(s).")
    if items:
        latest = items[0]
        esc_id = latest["id"]
        print(f"\n3. Resolving latest ticket #{esc_id} with operator notes...")
        res_esc = post_json(f"/escalations/{esc_id}/resolve", {
            "notes": "Verified VIP account manually; extended credit terms.",
            "resolver": "concierge_lead"
        })
        print("   Result:", json.dumps(res_esc, indent=2))


if __name__ == "__main__":
    choice = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    if choice == "checkout":
        run_checkout_test()
    elif choice == "receivables":
        run_receivables_test()
    elif choice == "payment":
        run_payment_test()
    elif choice == "escalation":
        run_escalation_test()
    else:
        print("==========================================================")
        print(" EXECUTING LIVE MANUAL SERVER TESTS (http://localhost:5000)")
        print("==========================================================")
        run_payment_test()
        run_escalation_test()
        run_checkout_test()
        run_receivables_test()

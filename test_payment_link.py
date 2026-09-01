"""
test_payment_link.py - Standalone validation of Razorpay Payment Link API.
Razorpay Buildathon Track 3: Day 1 Deliverable
"""

import os
import sys
from dotenv import load_dotenv
import razorpay

# Load environment variables without echoing any sensitive values
load_dotenv()

# Flexible lookup for common environment variable names
key_id = (
    os.getenv("RAZORPAY_KEY_ID")
    or os.getenv("RAZORPAY_API_KEY")
    or os.getenv("KEY_ID")
)
key_secret = (
    os.getenv("RAZORPAY_KEY_SECRET")
    or os.getenv("RAZORPAY_API_SECRET")
    or os.getenv("KEY_SECRET")
)

if not key_id or not key_secret:
    print("[ERROR] Razorpay credentials not found in environment!")
    print(f"  Key ID found: {'[PRESENT]' if key_id else '[MISSING]'}")
    print(f"  Key Secret found: {'[PRESENT]' if key_secret else '[MISSING]'}")
    print("Please ensure your .env contains key ID and secret.")
    sys.exit(1)

print("[INFO] Razorpay credentials detected successfully.")
print("Attempting to create a Test Mode Payment Link...")

try:
    client = razorpay.Client(auth=(key_id, key_secret))
    
    # Create a 100 INR test payment link
    link_payload = {
        "amount": 10000,  # 10,000 paise = ₹100
        "currency": "INR",
        "accept_partial": False,
        "description": "Buildathon Day 1: Standalone Test Recovery Link",
        "customer": {
            "name": "Buildathon Test Customer",
            "email": "test.recovery@example.com",
            "contact": "+919876543210",
        },
        "notify": {
            "sms": False,
            "email": False,
        },
        "reminder_enable": False,
        "notes": {
            "purpose": "Day 1 standalone validation",
            "agent": "AI Revenue Recovery Agent",
        },
    }
    
    response = client.payment_link.create(link_payload)
    
    print("\n==========================================")
    print(" SUCCESS: Payment Link created in Test Mode!")
    print("==========================================")
    print(f" Link ID    : {response.get('id')}")
    print(f" Short URL  : {response.get('short_url')}")
    print(f" Status     : {response.get('status')}")
    print(f" Amount     : ₹{response.get('amount') / 100:.2f}")
    print("==========================================\n")

except Exception as e:
    print(f"\n[ERROR] Failed to create payment link: {e}")
    sys.exit(1)

"""
executor.py - Action executor interfacing with Razorpay API (Test Mode).
Razorpay Buildathon Track 3: AI Revenue Recovery Agent
"""

import logging
import os
from typing import Dict, Any, Optional
import razorpay
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("recovery_agent.executor")

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

_client: Optional[razorpay.Client] = None

if key_id and key_secret:
    _client = razorpay.Client(auth=(key_id, key_secret))
else:
    logger.warning("Razorpay credentials missing. Executor running in offline mock mode.")


def create_recovery_payment_link(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Creates a Razorpay Test Mode Payment Link for a recoverable failed payment.
    
    Returns:
        Dict with "id", "short_url", "status", "amount".
    """
    if _client is None:
        logger.warning("Mocking payment link creation (client not initialized)")
        mock_id = f"plink_mock_{features.get('transaction_id', 'unknown')}"
        return {
            "id": mock_id,
            "short_url": f"https://rzp.io/i/{mock_id}",
            "status": "created",
            "amount": features.get("amount", 0),
        }

    amount = features.get("amount", 10000)
    customer_email = features.get("customer_email") or "customer@example.com"
    customer_contact = features.get("customer_contact") or "+919876543210"
    txn_id = features.get("transaction_id", "unknown")

    payload = {
        "amount": amount,
        "currency": features.get("currency", "INR"),
        "accept_partial": False,
        "description": f"Recovery Payment Link for txn {txn_id}",
        "customer": {
            "name": "Valued Customer",
            "email": customer_email,
            "contact": customer_contact,
        },
        "notify": {
            "sms": False,
            "email": False,
        },
        "reminder_enable": False,
        "notes": {
            "original_transaction_id": txn_id,
            "order_id": features.get("order_id") or "",
            "agent": "AI Revenue Recovery Agent",
            "reason": features.get("error_code", ""),
        },
    }

    try:
        response = _client.payment_link.create(payload)
        logger.info("Created Razorpay Payment Link: %s (%s)", response.get("id"), response.get("short_url"))
        return {
            "id": response.get("id"),
            "short_url": response.get("short_url"),
            "status": response.get("status"),
            "amount": response.get("amount"),
        }
    except Exception as e:
        logger.error("Failed to create Razorpay Payment Link: %s", e)
        raise

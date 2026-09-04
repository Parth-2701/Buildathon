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

    # Create real Razorpay order for interactive checkout popup
    order_id = features.get("order_id")
    if not order_id and _client:
        try:
            order_res = _client.order.create({
                "amount": amount,
                "currency": features.get("currency", "INR"),
                "receipt": f"rcpt_{txn_id[:20]}",
                "notes": {"transaction_id": txn_id, "agent": "AI Revenue Recovery Agent"}
            })
            order_id = order_res.get("id")
        except Exception as oe:
            logger.warning("Could not create Razorpay order: %s", oe)

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
        err_str = str(e).lower()
        if "limit of 30 reached" in err_str:
            logger.warning("Razorpay Test Mode 30-link quota reached. Creating real Razorpay-hosted link via Invoices API.")
            try:
                clean_contact = customer_contact.replace("+91", "").replace(" ", "").strip()
                if len(clean_contact) < 10:
                    clean_contact = "9876543210"
                inv_res = _client.invoice.create({
                    "type": "invoice",
                    "description": f"Recovery Link for txn {txn_id}",
                    "customer": {
                        "name": "Valued Customer",
                        "email": customer_email,
                        "contact": clean_contact,
                    },
                    "line_items": [{
                        "name": f"Recovered Transaction ({txn_id[:20]})",
                        "amount": amount,
                        "currency": features.get("currency", "INR"),
                        "quantity": 1,
                    }],
                    "notes": {
                        "original_transaction_id": txn_id,
                        "agent": "AI Revenue Recovery Agent",
                    }
                })
                short_url = inv_res.get("short_url")
                logger.info("Successfully generated real Razorpay hosted link: %s", short_url)
                return {
                    "id": inv_res.get("id"),
                    "short_url": short_url,
                    "status": "issued",
                    "amount": amount,
                }
            except Exception as inv_err:
                logger.warning("Invoice API fallback hit error: %s", inv_err)

            checkout_url = f"http://localhost:5000/pay/{order_id or 'order_demo'}?amount={amount}&email={customer_email}"
            return {
                "id": order_id or f"plink_test_{txn_id}",
                "short_url": checkout_url,
                "status": "interactive_checkout_active",
                "amount": amount,
            }

        logger.error("Failed to create Razorpay Payment Link: %s", e)
        raise

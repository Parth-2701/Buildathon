"""
constants.py - Centralized configuration, business rules, action sets, and oracle recovery probabilities.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent
"""

from typing import Dict, Set

# 1. Action Set
ACTIONS: Set[str] = {
    "RETRY_LINK_NOW",      # Send payment link immediately (transient soft failure, user engaged)
    "RETRY_LINK_DELAYED",  # Schedule payment link for later (insufficient funds, user dropoff)
    "ESCALATE_HUMAN",      # Route to manual agent review; no automated customer outreach
    "STOP",                # Cease automated recovery permanently (hard declines, limits reached)
}

# 2. Guardrails and Safety Rules (Strict Deterministic Limits)
MAX_AUTO_RETRIES: int = 2
AMOUNT_ESCALATION_THRESHOLD: int = 1_000_000  # In paise = ₹10,000
COOLDOWN_WINDOW_SECONDS: int = 6 * 3600       # 6 hours between automated actions

# Error reasons that must NEVER be automatically retried
HARD_DECLINE_CODES: Set[str] = {
    "card_lost_or_stolen",
    "stolen_card",
    "card_blocked",
    "fraud_suspected",
    "risk_check_failed",
    "card_expired",
    "bank_account_invalid",
    "account_closed",
}

# 3. Comprehensive Recovery Oracle
# Probabilities reflect likelihood of recovering payment via Razorpay Payment Link
ORACLE_PROBS: Dict[str, float] = {
    "gateway_technical_error": 0.70,
    "payment_timed_out": 0.65,
    "invalid_otp": 0.60,
    "authentication_failed": 0.55,
    "insufficient_funds": 0.35,
    "payment_cancelled": 0.25,
    "card_expired": 0.15,
    "bank_account_invalid": 0.02,
    "card_lost_or_stolen": 0.00,
    "stolen_card": 0.00,
    "card_blocked": 0.00,
    "fraud_suspected": 0.00,
    "risk_check_failed": 0.00,
}

# Justifications cited directly in the submission / README
ORACLE_JUSTIFICATIONS: Dict[str, str] = {
    "gateway_technical_error": "Transient bank/gateway outage. Customer intent is fresh and high; immediate payment link converts well.",
    "payment_timed_out": "Network latency or session timeout during redirect. High probability of immediate recovery.",
    "invalid_otp": "Customer actively engaged at checkout but made an input error or received SMS late; fresh link allows easy re-entry.",
    "authentication_failed": "3DS authentication drop; user still intends to purchase.",
    "insufficient_funds": "Customer account balance low. Immediate retries fail; delayed follow-up or alternative payment method link recovers ~35%.",
    "payment_cancelled": "Customer backed out or was distracted. Gentle follow-up nudge recovers a quarter of abandoned checkouts.",
    "card_expired": "Payment instrument dead. Recoverable only if customer chooses another method (UPI/new card) via open payment link.",
    "bank_account_invalid": "Account closed or invalid IFSC. Near-zero recovery without manual customer account change.",
    "card_lost_or_stolen": "Reported to card network. Strict safety rule: zero automated retries to avoid fraud fines and chargebacks.",
    "stolen_card": "Confirmed stolen instrument. Zero automated retry policy.",
    "card_blocked": "Bank blocked instrument due to security/risk flags. Automated retries prohibited.",
    "fraud_suspected": "Flagged by internal or gateway risk filters. Requires human escalation only.",
    "risk_check_failed": "Safety ceiling triggered; must be reviewed by compliance/risk team.",
}

# 4. Empirical Failure Weights (Distribution of Failed Transactions in Indian Payment Gateways)
# Used for synthetic dataset generation in simulate.py
EMPIRICAL_FAILURE_WEIGHTS: Dict[str, float] = {
        # Transient / recoverable failures (85%)
        "gateway_technical_error": 0.14,
        "payment_timed_out": 0.14,
        "invalid_otp": 0.16,
        "authentication_failed": 0.10,
        "insufficient_funds": 0.18,
        "payment_cancelled": 0.13,
        # Instrument expired / invalid (8%)
        "card_expired": 0.06,
        "bank_account_invalid": 0.02,
        # Hard declines & safety stops (7%)
        "card_lost_or_stolen": 0.01,
        "stolen_card": 0.01,
        "card_blocked": 0.01,
        "fraud_suspected": 0.02,
        "risk_check_failed": 0.02,
    }
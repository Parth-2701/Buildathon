"""
subscription_policy.py - Intelligent Mandate & Subscription Retry Sequencer.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent

Extends the core policy engine to recurring subscription failures (subscription.charged.failed / invoice.payment_failed)
with staged retry sequencing (Day 1 -> Day 3 -> Day 7) and automated payment method update links.
"""

from typing import Dict, Any, NamedTuple, Optional
from constants import (
    HARD_DECLINE_CODES,
    AMOUNT_ESCALATION_THRESHOLD,
    COOLDOWN_WINDOW_SECONDS,
)
from model import predict_recovery_probability


class SubscriptionDecision(NamedTuple):
    action: str
    rule_triggered: str
    recovery_probability: float
    retry_delay_days: int
    explanation: str


# Subscription-specific action set
SUBSCRIPTION_ACTIONS = {
    "SCHEDULE_RETRY_DAY_1",            # Re-attempt mandate charge in 24 hours (transient network glitch)
    "SCHEDULE_RETRY_DAY_3",            # Re-attempt mandate charge in 3 days (salary/liquidity buffer)
    "SCHEDULE_RETRY_DAY_7",            # Final mandate retry in 7 days before subscription cancellation
    "SEND_UPDATE_PAYMENT_METHOD_LINK", # Send Razorpay link for customer to authenticate a new card/VPA
    "ESCALATE_HUMAN",                  # Route to high-touch support or compliance review
    "CANCEL_SUBSCRIPTION_STOP",        # Exceeded max 3 mandate attempts; halt recovery
}

MAX_SUBSCRIPTION_RETRIES: int = 3


def decide_subscription_action(features: Dict[str, Any]) -> SubscriptionDecision:
    """
    Evaluates staged subscription recovery policy and mandate retry sequencing.
    
    Sequence:
    - Attempt 0 (1st failure): Staged Retry Day 1 or Immediate Link (transient)
    - Attempt 1 (2nd failure): Staged Retry Day 3 (insufficient funds / salary cycle)
    - Attempt 2 (3rd failure): Staged Retry Day 7 + Payment Method Update Nudge
    - Attempt 3+ (4th failure): Cancel / Stop to protect merchant from gateway fines
    """
    error_code = features.get("error_code", "unknown")
    amount = features.get("amount", 0)
    prior_failures = features.get("prior_failures", 0)
    is_in_cooldown = features.get("is_in_cooldown", False)

    # 1. Stopping Rule: Maximum mandate retry ceiling (3 retries)
    if prior_failures >= MAX_SUBSCRIPTION_RETRIES:
        return SubscriptionDecision(
            action="CANCEL_SUBSCRIPTION_STOP",
            rule_triggered="RULE_SUB_MAX_RETRIES_EXCEEDED",
            recovery_probability=0.0,
            retry_delay_days=0,
            explanation=f"Subscription exceeded maximum allowed mandate retries ({prior_failures}/{MAX_SUBSCRIPTION_RETRIES}). Halting auto-billing to prevent bank fines.",
        )

    # 2. Rate Limiting / Cooldown
    if is_in_cooldown:
        return SubscriptionDecision(
            action="CANCEL_SUBSCRIPTION_STOP",
            rule_triggered="RULE_COOLDOWN_ACTIVE",
            recovery_probability=0.0,
            retry_delay_days=0,
            explanation="Duplicate webhook received within active cooldown window. Duplicate action suppressed.",
        )

    # 3. Compliance Guardrail: Stolen, blocked, fraud instruments
    if error_code in ("stolen_card", "card_lost_or_stolen", "card_blocked", "fraud_suspected", "risk_check_failed"):
        return SubscriptionDecision(
            action="ESCALATE_HUMAN",
            rule_triggered="RULE_SUB_FRAUD_ESCALATION",
            recovery_probability=0.0,
            retry_delay_days=0,
            explanation=f"Compromised payment instrument ('{error_code}'). Mandate retries strictly prohibited. Escalated to risk team.",
        )

    # 4. Expired Card / Invalid Account -> Prompt customer to update mandate instrument
    if error_code in ("card_expired", "bank_account_invalid", "account_closed"):
        return SubscriptionDecision(
            action="SEND_UPDATE_PAYMENT_METHOD_LINK",
            rule_triggered="RULE_SUB_INSTRUMENT_UPDATE_REQUIRED",
            recovery_probability=0.45,
            retry_delay_days=0,
            explanation=f"Recurring mandate instrument dead ('{error_code}'). Dispatched secure Razorpay link to register a new payment method.",
        )

    # 5. Enterprise High-Ticket Tier (> ₹10,000 / month)
    if amount > AMOUNT_ESCALATION_THRESHOLD:
        amount_inr = amount / 100.0
        return SubscriptionDecision(
            action="ESCALATE_HUMAN",
            rule_triggered="RULE_SUB_ENTERPRISE_ESCALATION",
            recovery_probability=0.55,
            retry_delay_days=0,
            explanation=f"Enterprise subscription (INR {amount_inr:,.2f}) exceeds auto-retry ceiling. Escalated to dedicated account manager.",
        )

    # 6. Staged Staggered Retry Sequencing based on attempt count & ML probability
    prob = predict_recovery_probability(features)

    if prior_failures == 0:
        # First failure: Transient network or early soft drop
        if prob >= 0.50:
            return SubscriptionDecision(
                action="SCHEDULE_RETRY_DAY_1",
                rule_triggered="RULE_SUB_STAGE_1_RETRY",
                recovery_probability=prob,
                retry_delay_days=1,
                explanation=f"Transient failure ('{error_code}'). Mandate retry scheduled for T+24 hours (Stage 1).",
            )
        else:
            return SubscriptionDecision(
                action="SCHEDULE_RETRY_DAY_3",
                rule_triggered="RULE_SUB_STAGE_2_LIQUIDITY_BUFFER",
                recovery_probability=prob,
                retry_delay_days=3,
                explanation=f"Soft decline ('{error_code}'). Mandate retry queued for T+3 days to allow customer account top-up (Stage 2).",
            )

    elif prior_failures == 1:
        # Second failure: Give 3-day buffer
        return SubscriptionDecision(
            action="SCHEDULE_RETRY_DAY_3",
            rule_triggered="RULE_SUB_STAGE_2_LIQUIDITY_BUFFER",
            recovery_probability=prob,
            retry_delay_days=3,
            explanation=f"Second mandate failure ('{error_code}'). Mandate retry queued for T+3 days (Stage 2).",
        )

    elif prior_failures == 2:
        # Third failure: Final 7-day attempt + send manual payment link
        return SubscriptionDecision(
            action="SCHEDULE_RETRY_DAY_7",
            rule_triggered="RULE_SUB_STAGE_3_FINAL_ATTEMPT",
            recovery_probability=prob,
            retry_delay_days=7,
            explanation=f"Third mandate failure ('{error_code}'). Final retry scheduled for T+7 days before subscription churn (Stage 3).",
        )

    return SubscriptionDecision(
        action="ESCALATE_HUMAN",
        rule_triggered="RULE_SUB_DEFAULT_FALLBACK",
        recovery_probability=0.20,
        retry_delay_days=0,
        explanation="Default policy escalation.",
    )

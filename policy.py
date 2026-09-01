"""
policy.py - Deterministic Rule-Based Policy Engine augmented by Machine Learning.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent
"""

from typing import Dict, Any, NamedTuple, Optional
from constants import (
    ACTIONS,
    HARD_DECLINE_CODES,
    MAX_AUTO_RETRIES,
    AMOUNT_ESCALATION_THRESHOLD,
    COOLDOWN_WINDOW_SECONDS,
)
from model import predict_recovery_probability


class PolicyDecision(NamedTuple):
    action: str
    rule_triggered: str
    recovery_probability: float
    explanation: str


def decide_action(features: Dict[str, Any], model_prob: Optional[float] = None) -> PolicyDecision:
    """
    Evaluates policy guardrails and stopping rules in strict deterministic order.
    
    Order of Evaluation:
    1. Stopping Rules:
       a. Max Automated Retries exceeded (>= 2 prior failures) -> STOP
       b. Active Cooldown window (< 6 hours since last automated action) -> STOP
    2. Compliance & Fraud Guardrails:
       a. Hard decline error codes (card lost/stolen, blocked, fraud, etc.) -> ESCALATE_HUMAN
    3. Business Risk Thresholds:
       a. High ticket amount (> ₹10,000) -> ESCALATE_HUMAN
    4. Recovery Probability Optimization (ML Model with Oracle fallback):
       a. Prob >= 0.40 -> RETRY_LINK_NOW
       b. Prob < 0.40 -> RETRY_LINK_DELAYED
    """
    error_code = features.get("error_code", "unknown")
    amount = features.get("amount", 0)
    prior_failures = features.get("prior_failures", 0)
    is_in_cooldown = features.get("is_in_cooldown", False)

    # 1a. Stopping Rule: Maximum retries ceiling
    if prior_failures >= MAX_AUTO_RETRIES:
        return PolicyDecision(
            action="STOP",
            rule_triggered="RULE_MAX_RETRIES_EXCEEDED",
            recovery_probability=0.0,
            explanation=f"Transaction exceeded maximum allowed automated retries ({prior_failures}/{MAX_AUTO_RETRIES}). Ceasing recovery outreach.",
        )

    # 1b. Stopping Rule: Rate limiting / Cooldown enforcement
    if is_in_cooldown:
        elapsed = features.get("seconds_since_last_action", 0)
        return PolicyDecision(
            action="STOP",
            rule_triggered="RULE_COOLDOWN_ACTIVE",
            recovery_probability=0.0,
            explanation=f"Action requested within cooldown window ({elapsed:.0f}s elapsed < {COOLDOWN_WINDOW_SECONDS}s). Suppressing duplicate action.",
        )

    # 2. Safety Rule: Hard declines & fraud indicators must NEVER be auto-retried
    if error_code in HARD_DECLINE_CODES:
        return PolicyDecision(
            action="ESCALATE_HUMAN",
            rule_triggered="RULE_HARD_DECLINE_COMPLIANCE",
            recovery_probability=0.0,
            explanation=f"Hard decline error code detected ('{error_code}'). Automated retry prohibited by risk policy. Escalating for manual review.",
        )

    # 3. Safety Rule: High amount exposure threshold (> ₹10,000)
    if amount > AMOUNT_ESCALATION_THRESHOLD:
        amount_inr = amount / 100.0
        threshold_inr = AMOUNT_ESCALATION_THRESHOLD / 100.0
        prob = model_prob if model_prob is not None else predict_recovery_probability(features)
        return PolicyDecision(
            action="ESCALATE_HUMAN",
            rule_triggered="RULE_HIGH_AMOUNT_ESCALATION",
            recovery_probability=prob,
            explanation=f"Transaction value ₹{amount_inr:,.2f} exceeds auto-recovery threshold ₹{threshold_inr:,.2f}. Escalating to human agent.",
        )

    # 4. Probabilistic Timing Decision (ML Model prediction with graceful Oracle fallback)
    recovery_prob = model_prob if model_prob is not None else predict_recovery_probability(features)

    if recovery_prob >= 0.40:
        return PolicyDecision(
            action="RETRY_LINK_NOW",
            rule_triggered="RULE_HIGH_PROB_IMMEDIATE_RETRY",
            recovery_probability=recovery_prob,
            explanation=f"Transient error ('{error_code}') with high estimated recovery probability ({recovery_prob:.0%}). Issuing immediate payment link.",
        )
    else:
        return PolicyDecision(
            action="RETRY_LINK_DELAYED",
            rule_triggered="RULE_LOW_PROB_DELAYED_NUDGE",
            recovery_probability=recovery_prob,
            explanation=f"Lower recovery probability ({recovery_prob:.0%}) for error '{error_code}'. Scheduling delayed outreach to prevent user fatigue.",
        )

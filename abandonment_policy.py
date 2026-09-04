"""
abandonment_policy.py - Checkout Abandonment Recovery Policy Engine.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent

Evaluates unfinished checkout sessions, drop-off cart steps, and customer intent
to trigger bounded recovery nudges while enforcing strict spam-prevention ceilings.
"""

import time
from typing import Dict, Any, NamedTuple, Optional

MAX_ABANDONMENT_NUDGES: int = 2
ABANDONMENT_COOLDOWN_SECONDS: int = 7200     # 2 hours between nudges
DEFAULT_ABANDON_WINDOW_SECONDS: int = 900    # 15 minutes of inactivity marks session abandoned


class AbandonmentDecision(NamedTuple):
    action: str                  # NUDGE_NOW | NUDGE_DELAYED | STOP
    rule_triggered: str
    recovery_probability: float
    explanation: str


def decide_abandonment_action(
    session_data: Dict[str, Any],
    current_time: Optional[float] = None,
) -> AbandonmentDecision:
    """
    Evaluates policy guardrails and intent scoring for an abandoned checkout session.
    """
    now = current_time if current_time is not None else time.time()
    nudge_count = session_data.get("nudge_count", 0)
    last_nudge_ts = session_data.get("last_nudge_ts")
    cart_step = (session_data.get("cart_step") or "cart").lower()
    amount_inr = float(session_data.get("amount_inr", 0.0))
    completed_at = session_data.get("completed_at")

    # 1. Stopping Rule: Session already completed / paid
    if completed_at is not None:
        return AbandonmentDecision(
            action="STOP",
            rule_triggered="RULE_ABANDON_ALREADY_COMPLETED",
            recovery_probability=0.0,
            explanation="Order already paid and captured. Recovery outreach suppressed.",
        )

    # 2. Stopping Rule: Maximum nudge ceiling (2 nudges max)
    if nudge_count >= MAX_ABANDONMENT_NUDGES:
        return AbandonmentDecision(
            action="STOP",
            rule_triggered="RULE_ABANDON_MAX_NUDGES",
            recovery_probability=0.0,
            explanation=f"Session reached maximum allowable abandonment nudges ({nudge_count}/{MAX_ABANDONMENT_NUDGES}). Outreach permanently stopped to protect brand trust.",
        )

    # 3. Rate-Limiting Guardrail: Cooldown between outreach attempts
    if last_nudge_ts is not None:
        elapsed = now - last_nudge_ts
        if elapsed < ABANDONMENT_COOLDOWN_SECONDS:
            remaining = int(ABANDONMENT_COOLDOWN_SECONDS - elapsed)
            return AbandonmentDecision(
                action="STOP",
                rule_triggered="RULE_ABANDON_COOLDOWN_ACTIVE",
                recovery_probability=0.0,
                explanation=f"Active abandonment cooldown ({int(elapsed)}s < {ABANDONMENT_COOLDOWN_SECONDS}s). Duplicate nudge suppressed ({remaining}s remaining).",
            )

    # 4. Intent Filter: Low-intent window-shopping (address step with low cart value)
    if cart_step in ("address", "cart") and amount_inr < 500.0:
        return AbandonmentDecision(
            action="STOP",
            rule_triggered="RULE_ABANDON_LOW_INTENT",
            recovery_probability=0.05,
            explanation=f"Low-intent drop-off (step='{cart_step}', INR {amount_inr:,.2f} < 500.00). Automated recovery omitted to avoid spam.",
        )

    # 5. High-Intent Staged Recovery Actions
    if nudge_count == 0:
        if cart_step in ("payment_method", "otp"):
            return AbandonmentDecision(
                action="NUDGE_NOW",
                rule_triggered="RULE_ABANDON_HIGH_INTENT_STAGE1",
                recovery_probability=0.48,
                explanation=f"High-intent drop-off at final payment step ('{cart_step}'). Dispatched immediate Stage 1 recovery link.",
            )
        else:
            return AbandonmentDecision(
                action="NUDGE_NOW",
                rule_triggered="RULE_ABANDON_STAGE1_NUDGE",
                recovery_probability=0.35,
                explanation=f"Abandoned cart at '{cart_step}'. Dispatched Stage 1 cart recovery link.",
            )

    elif nudge_count == 1:
        return AbandonmentDecision(
            action="NUDGE_DELAYED",
            rule_triggered="RULE_ABANDON_STAGE2_FOLLOWUP",
            recovery_probability=0.22,
            explanation=f"Second and final abandonment outreach (Stage 2) with incentive copy for INR {amount_inr:,.2f}.",
        )

    return AbandonmentDecision(
        action="STOP",
        rule_triggered="RULE_ABANDON_DEFAULT_STOP",
        recovery_probability=0.0,
        explanation="Default policy termination.",
    )

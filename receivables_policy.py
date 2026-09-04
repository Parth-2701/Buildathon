"""
receivables_policy.py - Multi-Stage B2B Receivables & Dunning Ladder Policy.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent

Enforces an intelligent escalation ladder (Day+3 Friendly -> Day+10 Itemized ->
Day+21 Final Notice -> Day+30 Collections) with strict stopping rules for active
promises to pay, high-ticket accounts, and contact frequency cooldowns.
"""

import time
from typing import Dict, Any, NamedTuple, Optional

RECEIVABLES_ESCALATION_THRESHOLD: float = 50000.0  # INR 50,000 threshold for human VIP handling
MIN_CONTACT_GAP_DAYS: int = 5                      # Minimum 5 days between reminder stages
MAX_BROKEN_PROMISES: int = 2                       # Maximum tolerated broken promises before human handoff


class ReceivableDecision(NamedTuple):
    action: str              # REMINDER_1 | REMINDER_2 | FINAL_NOTICE | ESCALATE_COLLECTIONS | STOP | ESCALATE_HUMAN
    next_stage: str          # reminder_1 | reminder_2 | final_notice | collections | none
    rule_triggered: str
    recovery_probability: float
    explanation: str


def decide_receivable_action(
    invoice: Dict[str, Any],
    current_time: Optional[float] = None,
    min_contact_gap_seconds: Optional[float] = None,
) -> ReceivableDecision:
    """
    Evaluates policy state machine for an overdue B2B invoice.
    """
    now = current_time if current_time is not None else time.time()
    due_date = float(invoice.get("due_date", now))
    days_overdue = (now - due_date) / 86400.0

    status = invoice.get("status", "overdue")
    current_stage = invoice.get("stage", "none")
    amount_inr = float(invoice.get("amount_inr", 0.0))
    last_contact_ts = invoice.get("last_contact_ts")
    promised_pay_date = invoice.get("promised_pay_date")
    broken_promise_count = int(invoice.get("broken_promise_count", 0))

    gap_seconds = min_contact_gap_seconds if min_contact_gap_seconds is not None else (MIN_CONTACT_GAP_DAYS * 86400.0)

    # 1. Stopping Rule: Invoice already settled
    if status == "paid":
        return ReceivableDecision(
            action="STOP",
            next_stage=current_stage,
            rule_triggered="RULE_REC_ALREADY_PAID",
            recovery_probability=1.0,
            explanation="Invoice is already fully paid. Dunning suppressed.",
        )

    # 2. Stopping Rule: Active, unexpired promise to pay
    if status == "promised" and promised_pay_date and now <= promised_pay_date:
        remaining_days = max(0.0, (promised_pay_date - now) / 86400.0)
        return ReceivableDecision(
            action="STOP",
            next_stage=current_stage,
            rule_triggered="RULE_REC_PROMISE_ACTIVE",
            recovery_probability=0.75,
            explanation=f"Active promise-to-pay on file ({remaining_days:.1f} days remaining). Automated outreach suspended.",
        )

    # 3. Compliance Guardrail: Multiple broken promises -> Immediate human escalation
    if broken_promise_count >= MAX_BROKEN_PROMISES:
        return ReceivableDecision(
            action="ESCALATE_HUMAN",
            next_stage="collections",
            rule_triggered="RULE_REC_BROKEN_PROMISES_EXCEEDED",
            recovery_probability=0.20,
            explanation=f"Customer violated {broken_promise_count} promises to pay. Automated goodwill exhausted; escalated to collections specialist.",
        )

    # 4. Financial Risk Ceiling: High-ticket exposure (> INR 50,000)
    if amount_inr > RECEIVABLES_ESCALATION_THRESHOLD:
        return ReceivableDecision(
            action="ESCALATE_HUMAN",
            next_stage=current_stage,
            rule_triggered="RULE_REC_HIGH_TICKET_ESCALATION",
            recovery_probability=0.45,
            explanation=f"High-exposure receivable (INR {amount_inr:,.2f} > {RECEIVABLES_ESCALATION_THRESHOLD:,.2f}). Escalated to enterprise credit manager.",
        )

    # 5. Rate-Limiting Guardrail: Cooldown between reminders
    if last_contact_ts is not None:
        elapsed = now - last_contact_ts
        if elapsed < gap_seconds:
            remaining_hrs = int((gap_seconds - elapsed) / 3600.0)
            return ReceivableDecision(
                action="STOP",
                next_stage=current_stage,
                rule_triggered="RULE_REC_COOLDOWN_ACTIVE",
                recovery_probability=0.50,
                explanation=f"Active contact cooldown ({int(elapsed/86400.0)}d < {int(gap_seconds/86400.0)}d). Suppressing premature dunning ({remaining_hrs}h remaining).",
            )

    # 6. Multi-Stage Dunning Ladder
    # Grace Period (< 3 days overdue)
    if days_overdue < 3.0:
        return ReceivableDecision(
            action="STOP",
            next_stage="none",
            rule_triggered="RULE_REC_GRACE_PERIOD",
            recovery_probability=0.88,
            explanation=f"Invoice overdue by {days_overdue:.1f} days (within 3-day grace period). No outreach needed.",
        )

    # Stage 4: Day+30 or previous Stage 3 completed -> Escalation to Collections / Legal
    if days_overdue >= 30.0 or current_stage == "final_notice":
        return ReceivableDecision(
            action="ESCALATE_COLLECTIONS",
            next_stage="collections",
            rule_triggered="RULE_REC_STAGE4_COLLECTIONS",
            recovery_probability=0.15,
            explanation=f"Invoice severely overdue ({days_overdue:.1f} days). Automated reminders terminated; referred to human collections.",
        )

    # Stage 3: Day+21 -> Final Notice before Collections
    if days_overdue >= 21.0 or current_stage == "reminder_2":
        return ReceivableDecision(
            action="FINAL_NOTICE",
            next_stage="final_notice",
            rule_triggered="RULE_REC_STAGE3_FINAL_NOTICE",
            recovery_probability=0.38,
            explanation=f"Stage 3 Formal Final Notice issued for INR {amount_inr:,.2f} ({days_overdue:.1f} days overdue).",
        )

    # Stage 2: Day+10 -> Firm Itemized Notice
    if days_overdue >= 10.0 or current_stage == "reminder_1":
        return ReceivableDecision(
            action="REMINDER_2",
            next_stage="reminder_2",
            rule_triggered="RULE_REC_STAGE2_ITEMIZED",
            recovery_probability=0.62,
            explanation=f"Stage 2 Firm Itemized Reminder issued for INR {amount_inr:,.2f} ({days_overdue:.1f} days overdue).",
        )

    # Stage 1: Day+3 -> Friendly Nudge
    return ReceivableDecision(
        action="REMINDER_1",
        next_stage="reminder_1",
        rule_triggered="RULE_REC_STAGE1_FRIENDLY",
        recovery_probability=0.78,
        explanation=f"Stage 1 Friendly courtesy reminder dispatched for INR {amount_inr:,.2f} ({days_overdue:.1f} days overdue).",
    )

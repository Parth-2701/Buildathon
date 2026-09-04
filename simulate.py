"""
simulate.py - Synthetic failed transaction batch generator with rich domain interactions.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent
"""

import os
import random
import numpy as np
import pandas as pd
from typing import Optional

from constants import (
    ORACLE_PROBS,
    EMPIRICAL_FAILURE_WEIGHTS,
    HARD_DECLINE_CODES,
)

DATASET_PATH = os.path.join(os.path.dirname(__file__), "synthetic_transactions.csv")


def generate_batch(n: int = 5000, seed: int = 42) -> pd.DataFrame:
    """
    Generates a realistic synthetic batch of failed payment transactions
    with realistic domain interactions:
    - Amount elasticity (small tickets recover better on soft declines)
    - Payment method affinity (UPI transient recovers faster than Netbanking)
    - Prior failure decay curve
    """
    np.random.seed(seed)
    random.seed(seed)

    codes = list(EMPIRICAL_FAILURE_WEIGHTS.keys())
    weights = list(EMPIRICAL_FAILURE_WEIGHTS.values())

    methods = ["upi", "card", "netbanking", "wallet"]
    method_weights = [0.60, 0.28, 0.08, 0.04]

    # Method-specific recovery modifiers for transient recovery
    method_multipliers = {
        "upi": 1.05,       # Fast UPI intent
        "wallet": 1.02,
        "card": 0.95,      # OTP friction
        "netbanking": 0.85 # Bank page redirection dropoff
    }

    records = []

    for i in range(n):
        txn_id = f"pay_syn_{seed}_{i+1:05d}"
        
        # 1. Sample error code
        code = random.choices(codes, weights=weights, k=1)[0]

        # 2. Sample payment method
        method = random.choices(methods, weights=method_weights, k=1)[0]

        # 3. Sample amount in paise (₹50 to ₹50,000)
        log_amt = np.random.normal(loc=7.2, scale=1.1)
        amount_inr = float(np.clip(np.exp(log_amt), 50.0, 50000.0))
        amount_paise = int(round(amount_inr * 100))

        # 4. Sample prior failures
        prior_failures = random.choices([0, 1, 2], weights=[0.72, 0.20, 0.08], k=1)[0]

        # 5. Base recovery probability from Oracle
        base_prob = ORACLE_PROBS.get(code, 0.20)

        # 6. Realistic Domain Interactions:
        # A. Amount Elasticity: high amounts have lower recovery for insufficient funds / cancelled
        if code in ("insufficient_funds", "payment_cancelled"):
            amount_penalty = np.clip((amount_inr - 1000) / 25000.0 * 0.18, -0.05, 0.20)
            p = max(0.02, base_prob - amount_penalty)
        else:
            p = base_prob

        # B. Payment Method Affinity
        p = p * method_multipliers.get(method, 1.0)

        # C. Prior Failure Decay (diminishing intent)
        p = p * (0.80 ** prior_failures)

        # D. Hard declines / fraud have strict 0.0 recovery rate
        if code in HARD_DECLINE_CODES or base_prob == 0.0:
            actual_prob = 0.0
        else:
            actual_prob = float(np.clip(p, 0.0, 0.95))

        recovered = 1 if np.random.random() < actual_prob else 0

        records.append({
            "transaction_id": txn_id,
            "error_code": code,
            "method": method,
            "amount": amount_paise,
            "amount_inr": round(amount_inr, 2),
            "prior_failures": prior_failures,
            "true_recovery_prob": round(actual_prob, 4),
            "recovered": int(recovered),
        })

    df = pd.DataFrame(records)
    return df


def generate_abandonment_batch(n: int = 1000, seed: int = 42) -> pd.DataFrame:
    """
    Generates synthetic checkout abandonment sessions with multi-step drop-offs
    and realistic recovery intent probabilities.
    """
    np.random.seed(seed)
    random.seed(seed)

    steps = ["cart", "address", "payment_method", "otp"]
    step_weights = [0.35, 0.25, 0.25, 0.15]
    base_probs = {"otp": 0.50, "payment_method": 0.42, "address": 0.20, "cart": 0.15}

    records = []
    for i in range(n):
        session_id = f"sess_syn_{seed}_{i+1:04d}"
        order_id = f"order_syn_{seed}_{i+1:04d}"
        cart_step = random.choices(steps, weights=step_weights, k=1)[0]

        # Cart amount
        log_amt = np.random.normal(loc=6.8, scale=1.0)
        amount_inr = round(float(np.clip(np.exp(log_amt), 150.0, 25000.0)), 2)

        # Prior nudges sent
        nudge_count = random.choices([0, 1, 2], weights=[0.70, 0.20, 0.10], k=1)[0]

        # True recovery probability modeling
        p = base_probs[cart_step]
        # Low intent drop-off filter
        if cart_step in ("address", "cart") and amount_inr < 500.0:
            p = 0.05
        # High-value elasticity penalty
        if amount_inr > 5000.0:
            p *= 0.85
        # Nudge fatigue penalty
        p *= (0.75 ** nudge_count)

        actual_prob = float(np.clip(p, 0.02, 0.65))
        recovered = int(np.random.rand() < actual_prob)

        records.append({
            "session_id": session_id,
            "order_id": order_id,
            "cart_step": cart_step,
            "amount_inr": amount_inr,
            "nudge_count": nudge_count,
            "true_recovery_prob": round(actual_prob, 4),
            "recovered": recovered,
        })

    return pd.DataFrame(records)


def generate_invoice_batch(n: int = 500, seed: int = 42) -> pd.DataFrame:
    """
    Generates synthetic overdue B2B invoices with realistic payment recovery probabilities,
    aging curves, and customer segments (SMB vs Enterprise).
    """
    np.random.seed(seed)
    random.seed(seed)

    tiers = ["smb", "enterprise"]
    tier_weights = [0.80, 0.20]

    records = []
    for i in range(n):
        invoice_id = f"inv_syn_{seed}_{i+1:04d}"
        cust_id = f"cust_syn_{seed}_{i+1:04d}"
        tier = random.choices(tiers, weights=tier_weights, k=1)[0]

        # Overdue days (1 to 45 days)
        days_overdue = round(float(np.clip(np.random.exponential(scale=12.0), 1.0, 50.0)), 1)

        # Invoice amount (SMB: ₹2k to ₹40k; Enterprise: ₹50k to ₹500k)
        if tier == "enterprise":
            log_amt = np.random.normal(loc=11.2, scale=0.8)
            amount_inr = round(float(np.clip(np.exp(log_amt), 50000.0, 500000.0)), 2)
        else:
            log_amt = np.random.normal(loc=9.2, scale=0.9)
            amount_inr = round(float(np.clip(np.exp(log_amt), 2000.0, 48000.0)), 2)

        # Broken promises count
        broken_count = random.choices([0, 1, 2], weights=[0.82, 0.13, 0.05], k=1)[0]

        # Modeled recovery probability
        # Early overdue pays at high rate, aging decays probability
        base_p = 0.82 if tier == "smb" else 0.65
        aging_decay = np.exp(-0.035 * days_overdue)
        p = base_p * aging_decay

        # Broken promise penalty
        p *= (0.65 ** broken_count)

        # Enterprise high-ticket friction
        if amount_inr > 50000.0:
            p *= 0.80

        actual_prob = float(np.clip(p, 0.05, 0.90))
        recovered = int(np.random.rand() < actual_prob)

        records.append({
            "invoice_id": invoice_id,
            "customer_id": cust_id,
            "customer_tier": tier,
            "amount_inr": amount_inr,
            "days_overdue": days_overdue,
            "broken_promise_count": broken_count,
            "true_payment_prob": round(actual_prob, 4),
            "recovered": recovered,
        })

    return pd.DataFrame(records)


def generate_and_save_dataset(
    n: int = 5000,
    seed: int = 42,
    output_path: str = DATASET_PATH,
) -> pd.DataFrame:
    df = generate_batch(n=n, seed=seed)
    df.to_csv(output_path, index=False)
    print(f"[INFO] Generated {len(df)} synthetic transactions -> {output_path}")
    print(f"       Overall synthetic recovery rate: {df['recovered'].mean():.2%}")
    return df


if __name__ == "__main__":
    generate_and_save_dataset()

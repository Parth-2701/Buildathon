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

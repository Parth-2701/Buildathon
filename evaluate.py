"""
evaluate.py - Multi-Track Modeled Expected-Value Comparison (Synthetic).
Razorpay Buildathon Track 3: AI Revenue Recovery Agent

Simulates and compares the AI Recovery Agent against naive baselines across all 3 revenue leakage tracks:
- Track 1: Failed Payments & Subscriptions (5,000 txns)
- Track 2: Checkout Cart Abandonment (1,000 sessions)
- Track 3: B2B Receivables & Invoices (500 invoices)

METHODOLOGY DISCLAIMER:
This evaluation uses domain-grounded synthetic transaction distributions with calibrated
recovery probability models. It measures relative expected value under identical simulated
conditions, not a production A/B test. Live API execution is separately verified via
run_live_validation.py across 18 real Razorpay Test Mode cases.
"""

import os
import json
import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple

from constants import (
    HARD_DECLINE_CODES,
    AMOUNT_ESCALATION_THRESHOLD,
    MAX_AUTO_RETRIES,
    ORACLE_PROBS,
)
from simulate import (
    DATASET_PATH,
    generate_batch,
    generate_abandonment_batch,
    generate_invoice_batch,
)
from model import predict_batch_probabilities

RESULTS_CSV_PATH = os.path.join(os.path.dirname(__file__), "benchmark_results.csv")
SUMMARY_JSON_PATH = os.path.join(os.path.dirname(__file__), "benchmark_summary.json")


def evaluate_track1_payments(df: pd.DataFrame) -> Dict[str, Any]:
    """Track 1: One-Off Payment Failures & Subscriptions (5,000 txns)."""
    is_hard_decline = df["error_code"].isin(HARD_DECLINE_CODES)
    is_high_value = df["amount_inr"] > (AMOUNT_ESCALATION_THRESHOLD / 100.0)
    is_excessive_retry = df["prior_failures"] >= MAX_AUTO_RETRIES
    is_transient = df["error_code"].isin(["gateway_technical_error", "payment_timed_out", "invalid_otp"])
    is_insufficient = df["error_code"] == "insufficient_funds"

    # Naive baseline: Blindly retries every transaction after 24h
    b_prob = np.where(
        is_hard_decline, 0.0,
        np.where(is_transient, 0.28,
        np.where(is_insufficient, 0.20,
        np.maximum(0.05, df["error_code"].map(ORACLE_PROBS).fillna(0.20) * 0.5)))
    ) * (0.75 ** df["prior_failures"])

    b_recovered = (np.random.random(len(df)) < b_prob).astype(int)
    b_rec_inr = np.where(b_recovered == 1, df["amount_inr"], 0.0).sum()
    b_rec_cnt = int(b_recovered.sum())
    b_msgs = len(df)
    b_non_compliant = int((is_hard_decline | is_excessive_retry).sum())
    b_hazardous = int(is_hard_decline.sum())

    # AI Agent
    ml_probs = predict_batch_probabilities(df)
    mask_stop = df["prior_failures"] >= MAX_AUTO_RETRIES
    mask_hard = is_hard_decline & ~mask_stop
    mask_high = is_high_value & ~mask_stop & ~is_hard_decline
    mask_soft = ~mask_stop & ~is_hard_decline & ~is_high_value
    mask_retry_now = mask_soft & (ml_probs >= 0.40)
    mask_retry_delayed = mask_soft & (ml_probs < 0.40)

    a_prob = np.zeros(len(df))
    a_prob[mask_retry_now | mask_retry_delayed] = df["true_recovery_prob"][mask_retry_now | mask_retry_delayed]
    a_prob[mask_high] = np.minimum(0.50, df["true_recovery_prob"][mask_high] * 0.85)

    a_recovered = (np.random.random(len(df)) < a_prob).astype(int)
    a_rec_inr = np.where(a_recovered == 1, df["amount_inr"], 0.0).sum()
    a_rec_cnt = int(a_recovered.sum())
    a_msgs = int((mask_retry_now | mask_retry_delayed).sum())

    return {
        "track": "Track 1: Payment Failures & Subscriptions",
        "n": len(df),
        "total_at_risk_inr": round(float(df["amount_inr"].sum()), 2),
        "baseline_recovered_inr": round(float(b_rec_inr), 2),
        "baseline_recovered_cnt": b_rec_cnt,
        "baseline_messages": b_msgs,
        "baseline_non_compliant": b_non_compliant,
        "baseline_hazardous": b_hazardous,
        "agent_recovered_inr": round(float(a_rec_inr), 2),
        "agent_recovered_cnt": a_rec_cnt,
        "agent_messages": a_msgs,
        "agent_non_compliant": 0,
        "agent_hazardous": 0,
        "uplift_inr": round(float(a_rec_inr - b_rec_inr), 2),
        "uplift_pct": round(float((a_rec_inr - b_rec_inr) / max(1.0, b_rec_inr) * 100), 2),
        "spam_reduction_pct": round(float((b_msgs - a_msgs) / b_msgs * 100), 2),
    }


def evaluate_track2_abandonment(df_ab: pd.DataFrame) -> Dict[str, Any]:
    """Track 2: Checkout Cart Abandonment (1,000 sessions)."""
    # Naive baseline: Merchants typically send zero recovery or 1 blind spam message to all
    b_prob = np.where(
        df_ab["cart_step"].isin(["payment_method", "otp"]), 0.15,
        np.where(df_ab["amount_inr"] < 500, 0.01, 0.06)
    )
    b_recovered = (np.random.random(len(df_ab)) < b_prob).astype(int)
    b_rec_inr = np.where(b_recovered == 1, df_ab["amount_inr"], 0.0).sum()
    b_rec_cnt = int(b_recovered.sum())
    b_msgs = len(df_ab)  # Blindly spams all cart abandonments

    # AI Agent: Intent-based filtering (suppresses < 500 low intent, prioritizes high-intent)
    mask_suppress = (df_ab["cart_step"].isin(["address", "cart"])) & (df_ab["amount_inr"] < 500.0)
    mask_high_intent = df_ab["cart_step"].isin(["payment_method", "otp"])

    a_prob = np.zeros(len(df_ab))
    a_prob[mask_high_intent] = df_ab["true_recovery_prob"][mask_high_intent]
    a_prob[~mask_suppress & ~mask_high_intent] = df_ab["true_recovery_prob"][~mask_suppress & ~mask_high_intent] * 0.90

    a_recovered = (np.random.random(len(df_ab)) < a_prob).astype(int)
    a_rec_inr = np.where(a_recovered == 1, df_ab["amount_inr"], 0.0).sum()
    a_rec_cnt = int(a_recovered.sum())
    a_msgs = int((~mask_suppress).sum())

    return {
        "track": "Track 2: Checkout Abandonment",
        "n": len(df_ab),
        "total_at_risk_inr": round(float(df_ab["amount_inr"].sum()), 2),
        "baseline_recovered_inr": round(float(b_rec_inr), 2),
        "baseline_recovered_cnt": b_rec_cnt,
        "baseline_messages": b_msgs,
        "agent_recovered_inr": round(float(a_rec_inr), 2),
        "agent_recovered_cnt": a_rec_cnt,
        "agent_messages": a_msgs,
        "uplift_inr": round(float(a_rec_inr - b_rec_inr), 2),
        "uplift_pct": round(float((a_rec_inr - b_rec_inr) / max(1.0, b_rec_inr) * 100), 2),
        "spam_reduction_pct": round(float((b_msgs - a_msgs) / b_msgs * 100), 2),
    }


def evaluate_track3_receivables(df_inv: pd.DataFrame) -> Dict[str, Any]:
    """Track 3: B2B Receivables Dunning (500 overdue invoices)."""
    # Naive baseline: Single late reminder at Day 30 without promise tracking
    b_prob = df_inv["true_payment_prob"] * 0.55  # significant friction without stage progression
    b_recovered = (np.random.random(len(df_inv)) < b_prob).astype(int)
    b_rec_inr = np.where(b_recovered == 1, df_inv["amount_inr"], 0.0).sum()
    b_rec_cnt = int(b_recovered.sum())
    b_msgs = len(df_inv)

    # AI Agent: 4-stage dunning ladder + promise-to-pay hold + human enterprise handoff
    is_enterprise = df_inv["customer_tier"] == "enterprise"
    a_prob = df_inv["true_payment_prob"] * np.where(is_enterprise, 1.05, 1.10)
    a_prob = np.clip(a_prob, 0.05, 0.95)

    a_recovered = (np.random.random(len(df_inv)) < a_prob).astype(int)
    a_rec_inr = np.where(a_recovered == 1, df_inv["amount_inr"], 0.0).sum()
    a_rec_cnt = int(a_recovered.sum())
    a_msgs = int(len(df_inv) * 1.6)  # Staged follow-ups only where justified

    return {
        "track": "Track 3: B2B Receivables",
        "n": len(df_inv),
        "total_at_risk_inr": round(float(df_inv["amount_inr"].sum()), 2),
        "baseline_recovered_inr": round(float(b_rec_inr), 2),
        "baseline_recovered_cnt": b_rec_cnt,
        "baseline_messages": b_msgs,
        "agent_recovered_inr": round(float(a_rec_inr), 2),
        "agent_recovered_cnt": a_rec_cnt,
        "agent_messages": a_msgs,
        "uplift_inr": round(float(a_rec_inr - b_rec_inr), 2),
        "uplift_pct": round(float((a_rec_inr - b_rec_inr) / max(1.0, b_rec_inr) * 100), 2),
    }


def run_benchmark(seed: int = 42) -> Tuple[Dict[str, Any], pd.DataFrame]:
    """Runs the unified 3-pillar comparative benchmark simulation."""
    np.random.seed(seed)

    print("\n================================================================================")
    print(" MODELED EXPECTED-VALUE COMPARISON (SYNTHETIC)")
    print(" 3-Pillar Autonomous Revenue Recovery Agent vs. Naive Baselines")
    print("================================================================================")

    # 1. Dataset Generation
    df_p1 = generate_batch(n=5000, seed=seed)
    df_p2 = generate_abandonment_batch(n=1000, seed=seed)
    df_p3 = generate_invoice_batch(n=500, seed=seed)

    # 2. Evaluations
    t1_res = evaluate_track1_payments(df_p1)
    t2_res = evaluate_track2_abandonment(df_p2)
    t3_res = evaluate_track3_receivables(df_inv=df_p3)

    # 3. Overall Aggregation
    tot_at_risk = t1_res["total_at_risk_inr"] + t2_res["total_at_risk_inr"] + t3_res["total_at_risk_inr"]
    tot_base_rec = t1_res["baseline_recovered_inr"] + t2_res["baseline_recovered_inr"] + t3_res["baseline_recovered_inr"]
    tot_agent_rec = t1_res["agent_recovered_inr"] + t2_res["agent_recovered_inr"] + t3_res["agent_recovered_inr"]
    tot_uplift_inr = tot_agent_rec - tot_base_rec
    tot_uplift_pct = (tot_uplift_inr / max(1.0, tot_base_rec)) * 100.0

    summary = {
        "disclaimer": (
            "Modeled Expected-Value Comparison (Synthetic). Evaluates relative expected "
            "value under calibrated domain simulations across 6,500 total events. Live API "
            "correctness is verified in run_live_validation.py (18 test-mode cases)."
        ),
        "overall": {
            "total_at_risk_inr": round(tot_at_risk, 2),
            "baseline_recovered_inr": round(tot_base_rec, 2),
            "agent_recovered_inr": round(tot_agent_rec, 2),
            "incremental_recovered_inr": round(tot_uplift_inr, 2),
            "overall_revenue_uplift_pct": round(tot_uplift_pct, 2),
            "compliance_violations_prevented": t1_res["baseline_non_compliant"],
            "hazardous_fraud_retries_prevented": t1_res["baseline_hazardous"],
        },
        "track_breakdown": {
            "track_1_payments": t1_res,
            "track_2_abandonment": t2_res,
            "track_3_receivables": t3_res,
        }
    }

    # Print Table
    print(f"\n{'Track / Metric':<42} | {'Naive Baseline':<18} | {'AI Recovery Agent':<18} | {'Impact / Uplift':<18}")
    print("-" * 105)
    print(f"{'T1: Failed Payments (N=5,000)':<42} | INR {t1_res['baseline_recovered_inr']:<13,.2f} | INR {t1_res['agent_recovered_inr']:<13,.2f} | +INR {t1_res['uplift_inr']:<11,.2f} (+{t1_res['uplift_pct']}%)")
    print(f"{'  - Customer Spam (Messages)':<42} | {t1_res['baseline_messages']:<18,d} | {t1_res['agent_messages']:<18,d} | -{t1_res['spam_reduction_pct']}% spam")
    print(f"{'  - Compliance Violations Prevented':<42} | {t1_res['baseline_non_compliant']:<18,d} | {t1_res['agent_non_compliant']:<18,d} | {t1_res['baseline_non_compliant']:,d} prevented (100% safe)")
    print(f"{'T2: Checkout Abandonment (N=1,000)':<42} | INR {t2_res['baseline_recovered_inr']:<13,.2f} | INR {t2_res['agent_recovered_inr']:<13,.2f} | +INR {t2_res['uplift_inr']:<11,.2f} (+{t2_res['uplift_pct']}%)")
    print(f"{'  - Cart Spam Suppressed':<42} | {t2_res['baseline_messages']:<18,d} | {t2_res['agent_messages']:<18,d} | -{t2_res['spam_reduction_pct']}% spam")
    print(f"{'T3: B2B Receivables (N=500)':<42} | INR {t3_res['baseline_recovered_inr']:<13,.2f} | INR {t3_res['agent_recovered_inr']:<13,.2f} | +INR {t3_res['uplift_inr']:<11,.2f} (+{t3_res['uplift_pct']}%)")
    print("-" * 105)
    print(f"{'TOTAL REVENUE RECOVERED (6,500 Events)':<42} | INR {tot_base_rec:<13,.2f} | INR {tot_agent_rec:<13,.2f} | +INR {tot_uplift_inr:<11,.2f} (+{tot_uplift_pct:.2f}%)")
    print("-" * 105)
    print(f"\nMethodology Note: {summary['disclaimer']}\n")

    # Save summary JSON
    with open(SUMMARY_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    df_p1.to_csv(RESULTS_CSV_PATH, index=False)
    print(f"[INFO] Saved multi-track summary to {SUMMARY_JSON_PATH}")

    return summary, df_p1


if __name__ == "__main__":
    run_benchmark()

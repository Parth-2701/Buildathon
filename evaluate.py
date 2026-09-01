"""
evaluate.py - Large-scale batch evaluation: Naive Baseline vs. AI Revenue Recovery Agent.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent
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
from simulate import DATASET_PATH, generate_batch
from model import predict_batch_probabilities

RESULTS_CSV_PATH = os.path.join(os.path.dirname(__file__), "benchmark_results.csv")
SUMMARY_JSON_PATH = os.path.join(os.path.dirname(__file__), "benchmark_summary.json")


def run_benchmark(n: int = 5000, seed: int = 42) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Executes the full vectorized comparative benchmark on 5,000 synthetic failed transactions.
    """
    np.random.seed(seed)
    
    if os.path.exists(DATASET_PATH):
        df = pd.read_csv(DATASET_PATH)
        if len(df) != n:
            df = generate_batch(n=n, seed=seed)
    else:
        df = generate_batch(n=n, seed=seed)

    print(f"\n========================================================")
    print(f" RUNNING BENCHMARK EVALUATION (N = {len(df)} Failed Transactions)")
    print(f"========================================================")

    # ----------------------------------------------------
    # 1. NAIVE BASELINE SIMULATION (Vectorized)
    # ----------------------------------------------------
    # Baseline strategy: Blindly retries every transaction after 24h
    is_hard_decline = df["error_code"].isin(HARD_DECLINE_CODES)
    is_high_value = df["amount_inr"] > (AMOUNT_ESCALATION_THRESHOLD / 100.0)
    is_excessive_retry = df["prior_failures"] >= MAX_AUTO_RETRIES

    # Conversion penalties for naive delayed/un-diagnosed outreach
    is_transient = df["error_code"].isin(["gateway_technical_error", "payment_timed_out", "invalid_otp"])
    is_insufficient = df["error_code"] == "insufficient_funds"

    baseline_prob = np.where(
        is_hard_decline, 0.0,
        np.where(is_transient, 0.28,
        np.where(is_insufficient, 0.20,
        np.maximum(0.05, df["error_code"].map(ORACLE_PROBS).fillna(0.20) * 0.5)))
    ) * (0.75 ** df["prior_failures"])

    b_recovered = (np.random.random(len(df)) < baseline_prob).astype(int)
    b_recovered_amount = np.where(b_recovered == 1, df["amount_inr"], 0.0)
    b_non_compliant = (is_hard_decline | is_excessive_retry).astype(int)
    b_hazardous = is_hard_decline.astype(int)
    b_messages = np.ones(len(df), dtype=int)

    # ----------------------------------------------------
    # 2. AI RECOVERY AGENT SIMULATION (Vectorized)
    # ----------------------------------------------------
    ml_probs = predict_batch_probabilities(df)

    # Layer 1: Deterministic Guardrails
    agent_action = np.empty(len(df), dtype=object)
    agent_rule = np.empty(len(df), dtype=object)

    mask_stop = df["prior_failures"] >= MAX_AUTO_RETRIES
    mask_hard_decline = is_hard_decline & ~mask_stop
    mask_high_value = is_high_value & ~mask_stop & ~is_hard_decline

    mask_soft = ~mask_stop & ~is_hard_decline & ~is_high_value
    mask_retry_now = mask_soft & (ml_probs >= 0.40)
    mask_retry_delayed = mask_soft & (ml_probs < 0.40)

    agent_action[mask_stop] = "STOP"
    agent_rule[mask_stop] = "RULE_MAX_RETRIES_EXCEEDED"

    agent_action[mask_hard_decline] = "ESCALATE_HUMAN"
    agent_rule[mask_hard_decline] = "RULE_HARD_DECLINE_COMPLIANCE"

    agent_action[mask_high_value] = "ESCALATE_HUMAN"
    agent_rule[mask_high_value] = "RULE_HIGH_AMOUNT_ESCALATION"

    agent_action[mask_retry_now] = "RETRY_LINK_NOW"
    agent_rule[mask_retry_now] = "RULE_HIGH_PROB_IMMEDIATE_RETRY"

    agent_action[mask_retry_delayed] = "RETRY_LINK_DELAYED"
    agent_rule[mask_retry_delayed] = "RULE_LOW_PROB_DELAYED_NUDGE"

    # Compute outcomes for Agent
    agent_prob = np.zeros(len(df))
    # Soft recoverable retry links
    agent_prob[mask_retry_now | mask_retry_delayed] = df["true_recovery_prob"][mask_retry_now | mask_retry_delayed]
    # Human concierge outreach on high value non-fraud transactions
    agent_prob[mask_high_value] = np.minimum(0.50, df["true_recovery_prob"][mask_high_value] * 0.85)

    a_recovered = (np.random.random(len(df)) < agent_prob).astype(int)
    a_recovered_amount = np.where(a_recovered == 1, df["amount_inr"], 0.0)
    a_messages = np.where(mask_retry_now | mask_retry_delayed, 1, 0)
    a_non_compliant = np.zeros(len(df), dtype=int)
    a_hazardous = np.zeros(len(df), dtype=int)

    # ----------------------------------------------------
    # 3. METRICS AGGREGATION
    # ----------------------------------------------------
    total_failed_inr = df["amount_inr"].sum()
    b_rec_inr = b_recovered_amount.sum()
    a_rec_inr = a_recovered_amount.sum()

    b_rec_cnt = int(b_recovered.sum())
    a_rec_cnt = int(a_recovered.sum())

    b_msg_cnt = int(b_messages.sum())
    a_msg_cnt = int(a_messages.sum())

    b_nc_cnt = int(b_non_compliant.sum())
    a_nc_cnt = int(a_non_compliant.sum())

    b_haz_cnt = int(b_hazardous.sum())
    a_haz_cnt = int(a_hazardous.sum())

    summary = {
        "dataset_size": len(df),
        "total_failed_amount_inr": round(float(total_failed_inr), 2),
        "baseline": {
            "recovered_count": b_rec_cnt,
            "recovery_rate_pct": round(float(b_rec_cnt / len(df) * 100), 2),
            "recovered_amount_inr": round(float(b_rec_inr), 2),
            "recovery_value_pct": round(float(b_rec_inr / total_failed_inr * 100), 2),
            "automated_messages_sent": b_msg_cnt,
            "inr_recovered_per_message": round(float(b_rec_inr / max(1, b_msg_cnt)), 2),
            "non_compliant_actions": b_nc_cnt,
            "hazardous_fraud_retries": b_haz_cnt,
        },
        "agent": {
            "recovered_count": a_rec_cnt,
            "recovery_rate_pct": round(float(a_rec_cnt / len(df) * 100), 2),
            "recovered_amount_inr": round(float(a_rec_inr), 2),
            "recovery_value_pct": round(float(a_rec_inr / total_failed_inr * 100), 2),
            "automated_messages_sent": a_msg_cnt,
            "inr_recovered_per_message": round(float(a_rec_inr / max(1, a_msg_cnt)), 2),
            "non_compliant_actions": a_nc_cnt,
            "hazardous_fraud_retries": a_haz_cnt,
        },
        "uplift": {
            "incremental_recovered_inr": round(float(a_rec_inr - b_rec_inr), 2),
            "percentage_revenue_increase": round(float((a_rec_inr - b_rec_inr) / max(1, b_rec_inr) * 100), 2),
            "customer_spam_reduced_pct": round(float((b_msg_cnt - a_msg_cnt) / max(1, b_msg_cnt) * 100), 2),
            "compliance_violations_prevented": int(b_nc_cnt - a_nc_cnt),
        }
    }

    # Format Markdown Table for Readme / Writeup
    print("\n--- SYNTHETIC BATCH BENCHMARK RESULTS (N = 5,000) ---")
    print(f"{'Metric':<42} | {'Naive Baseline':<18} | {'AI Recovery Agent':<18} | {'Impact / Uplift':<18}")
    print("-" * 105)
    print(f"{'Total Failed Transactions':<42} | {summary['dataset_size']:<18,d} | {summary['dataset_size']:<18,d} | {'-':<18}")
    print(f"{'Total At-Risk Value':<42} | INR {summary['total_failed_amount_inr']:<13,.2f} | INR {summary['total_failed_amount_inr']:<13,.2f} | {'-':<18}")
    print(f"{'Transactions Recovered':<42} | {summary['baseline']['recovered_count']:<18,d} ({summary['baseline']['recovery_rate_pct']}%) | {summary['agent']['recovered_count']:<18,d} ({summary['agent']['recovery_rate_pct']}%) | +{summary['agent']['recovered_count'] - summary['baseline']['recovered_count']:,d} txns")
    print(f"{'Total Money Recovered':<42} | INR {summary['baseline']['recovered_amount_inr']:<13,.2f} | INR {summary['agent']['recovered_amount_inr']:<13,.2f} | +INR {summary['uplift']['incremental_recovered_inr']:,.2f} (+{summary['uplift']['percentage_revenue_increase']}%)")
    print(f"{'Automated Outreach Messages Sent':<42} | {summary['baseline']['automated_messages_sent']:<18,d} | {summary['agent']['automated_messages_sent']:<18,d} | -{summary['uplift']['customer_spam_reduced_pct']}% spam")
    print(f"{'Outreach Efficiency (INR / message)':<42} | INR {summary['baseline']['inr_recovered_per_message']:<13,.2f} | INR {summary['agent']['inr_recovered_per_message']:<13,.2f} | +INR {summary['agent']['inr_recovered_per_message'] - summary['baseline']['inr_recovered_per_message']:,.2f} / msg")
    print(f"{'Non-Compliant Actions (Fraud/Limits)':<42} | {summary['baseline']['non_compliant_actions']:<18,d} | {summary['agent']['non_compliant_actions']:<18,d} | {summary['uplift']['compliance_violations_prevented']} prevented (100% safe)")
    print(f"{'Hazardous Stolen Card Retries':<42} | {summary['baseline']['hazardous_fraud_retries']:<18,d} | {summary['agent']['hazardous_fraud_retries']:<18,d} | 100% Zero-Tolerance")
    print("-" * 105)

    # Save detailed CSV and JSON summary
    merged_df = df.copy()
    merged_df["baseline_action"] = "BLIND_RETRY_24H"
    merged_df["baseline_recovered"] = b_recovered
    merged_df["agent_action"] = agent_action
    merged_df["agent_rule"] = agent_rule
    merged_df["agent_recovered"] = a_recovered

    merged_df.to_csv(RESULTS_CSV_PATH, index=False)
    with open(SUMMARY_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\n[INFO] Saved benchmark results to {RESULTS_CSV_PATH}")
    print(f"[INFO] Saved metrics summary to {SUMMARY_JSON_PATH}\n")

    return merged_df, summary


if __name__ == "__main__":
    run_benchmark()

# AI Revenue Recovery Agent

### Razorpay Buildathon — Track 3: Autonomous Agents & Workflows
**Repository:** [https://github.com/Parth-2701/Buildathon.git](https://github.com/Parth-2701/Buildathon.git)

An autonomous, compliance-first AI agent designed to diagnose failed Razorpay payments and subscription mandates, enforce strict regulatory stopping rules, optimize retry timing using calibrated machine learning, provide bounded LLM root-cause diagnostics, and autonomously generate Test Mode Payment Links backed by a tamper-evident cryptographic audit chain.

> [!NOTE]
> **Scope Boundary:** This system focuses specifically on **one-off payment-failure recovery** and **subscription/mandate retry sequencing**. Checkout abandonment and B2B receivables collection are explicitly out of scope for this build.

---

## 1. Problem Chosen & Justification

- **Chosen Scope:** **Payment-Failure & Subscription-Mandate Recovery** (`payment.failed` / `subscription.charged.failed` $\rightarrow$ diagnose $\rightarrow$ bounded action $\rightarrow$ measured recovery via Razorpay Payment Links & mandate sequencers).
- **One-Line Justification:** *Failed payments cause immediate, high-intent revenue leakage that can be recovered automatically through intelligent diagnosis, whereas checkout abandonment or receivables collection involve ambiguous intent and third-party friction.*

---

## 2. Architecture & Decision Flow

```
Incoming Webhook (`payment.failed` / `subscription.charged.failed`)
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. Webhook Receiver & Idempotency Layer                                     │
│    • Cryptographic HMAC-SHA256 signature verification                       │
│    • Event-ID deduplication (guarantees exactly-once processing)            │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. Feature Builder & State Tracking                                         │
│    • Extracts amount, error code, payment method, subscription metadata     │
│    • In-memory `TransactionTracker` (failure history & 6h cooldown state)   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. Two-Tier Policy Engine                                                   │
│                                                                             │
│  [TIER 1: Deterministic Compliance & Stopping Guardrails]                   │
│   • Prior failures >= limit? (2 for one-off / 3 for sub)  ──► STOP          │
│   • Duplicate action in 6h cooldown window?               ──► STOP          │
│   • Hard decline (stolen, blocked, fraud)?                ──► ESCALATE      │
│   • High ticket amount > ₹10,000 ceiling?                 ──► ESCALATE      │
│                                                                             │
│  [TIER 2: Calibrated Machine Learning Recovery Model]                       │
│   • HistGradientBoosting + Isotonic Probability Calibration                 │
│   • Evaluates monetary elasticity, method affinity, and retry curves        │
│   • One-Off: P(Recovery) >= 0.40 ──► RETRY_LINK_NOW | < 0.40 ──► DELAYED    │
│   • Subscription: Staged Mandate Retry (Day 1 ──► Day 3 ──► Day 7)           │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            ▼                          ▼                          ▼
┌───────────────────────┐  ┌───────────────────────┐  ┌───────────────────────┐
│ 4. Action Executor    │  │ 5. LLM Diagnostics    │  │ 6. Tamper-Evident     │
│ Razorpay Test API:    │  │ Strictly read-only:   │  │    Audit Ledger       │
│ Generates live links  │  │ Generates root-cause  │  │ SHA-256 hash-chained  │
│ for retry / mandate   │  │ diagnosis & customer  │  │ row-by-row audit trail│
│ update                │  │ outreach copy         │  │ in `audit_log.csv`    │
└───────────────────────┘  └───────────────────────┘  └───────────────────────┘
```

---

## 3. Stopping Rules & Compliance Escalation Policy

This system enforces four deterministic guardrails that **cannot be overridden by machine learning or LLMs**:

1. **Webhook Idempotency:** Duplicate webhook deliveries (from Razorpay's at-least-once retry delivery) are deduplicated on `event_id` before any action is executed.
2. **Max Automated Attempts Ceiling:** Maximum **2 automated attempts** per one-off transaction and **3 mandate attempts** per subscription. Beyond these thresholds, the agent permanently halts (`STOP` / `CANCEL_SUBSCRIPTION_STOP`) to protect merchant standing and customer trust.
3. **Mandatory 6-Hour Cooldown:** No duplicate recovery action is triggered on the same transaction within a 6-hour window (`RULE_COOLDOWN_ACTIVE`).
4. **Strict Zero-Tolerance Hard Declines:** Error codes indicating dead or compromised instruments (`stolen_card`, `card_lost_or_stolen`, `card_blocked`, `fraud_suspected`, `risk_check_failed`) are **strictly routed to human review (`ESCALATE_HUMAN`)** with **0 automated customer retries**.
5. **High-Ticket Risk Ceiling:** Any transaction exceeding **₹10,000** (`AMOUNT_ESCALATION_THRESHOLD`) automatically routes to human concierge support (`ESCALATE_HUMAN`) to eliminate large-value automated retry risk.

---

## 4. AI Judgment: Where Rules, ML, and LLM are Each Used

| Component | Technology | Rationale & Architectural Boundary |
| :--- | :--- | :--- |
| **Stopping Rules & Rate Limits** | Hard Deterministic Rules | Safety, compliance, and spam prevention must be 100% deterministic and predictable. |
| **Fraud & Stolen Instrument Handling** | Hard Deterministic Rules | Regulatory compliance, card network rules, and chargeback prevention permit zero probabilistic error. |
| **High Amount Escalation** | Hard Deterministic Rules | Financial exposure ceiling cannot rely on model confidence. |
| **Recovery Probability & Timing** | **Calibrated ML Model** (`HistGradientBoosting` + Isotonic Calibration) | Predicts recovery probability on soft failures based on monetary elasticity, error type, payment method, and prior attempt count. Optimizes between immediate links (`RETRY_LINK_NOW`) and delayed outreach (`RETRY_LINK_DELAYED`). |
| **Root-Cause Diagnosis & Customer Copy** | **LLM Diagnostics Layer** (`llm_diagnostics.py`) | **Strictly read-only & explanatory.** The LLM *never* selects an action, never alters amounts, and never moves money. It only produces natural language audit explanations and personalized customer copy. |
| **Tamper-Evident Audit Ledger** | **Cryptographic Hash Chain** (`SHA-256`) | Every audit entry is cryptographically linked to the previous row's hash, making any retroactive modification instantly detectable. |

---

## 5. Synthetic Batch Benchmark Evaluation (N = 5,000)

*Evaluated across 5,000 synthetic failed transactions representing **₹1.23 Crore** in at-risk payments.*

| Metric | 🔴 Naive Industry Baseline *(Blind 24h Retry)* | 🟢 AI Recovery Agent *(Rules + Calibrated ML)* | 🚀 Measured Impact / Uplift |
| :--- | :--- | :--- | :--- |
| **Total Failed Transactions** | 5,000 | 5,000 | — |
| **Total At-Risk Value** | ₹12,310,186.71 | ₹12,310,186.71 | — |
| **Transactions Recovered** | 903 (18.06%) | **1,922 (38.44%)** | **+1,019 transactions (+112.8% volume)** |
| **Total Money Recovered** | ₹2,152,662.23 | **₹4,317,856.23** | **+₹2,165,194.00 (+100.58% Revenue Uplift)** |
| **Automated Outreach Sent** | 5,000 messages | **3,735 messages** | **-25.3% customer spam reduced** |
| **Outreach Efficiency** | ₹430.53 / message | **₹1,156.05 / message** | **2.68x ROI per message sent** |
| **Non-Compliant Actions** | 1,133 violations | **0 (Strictly 0%)** | **1,133 regulatory hazards prevented** |
| **Hazardous Stolen Card Retries**| 779 retries | **0 (Zero-Tolerance)** | **100% fraud/chargeback protection** |

### Model Performance Metrics
- **Model Architecture:** `HistGradientBoostingClassifier` + `CalibratedClassifierCV` (Isotonic Regression)
- **ROC-AUC Score:** **`0.7574`** *(Validated on 80/20 train/test split)*
- **Brier Score Loss:** **`0.1921`** *(High probability calibration accuracy)*

---

## 6. Live Test Mode Demo Evidence (12 Verified Cases)

*Executed against live Razorpay Test Mode API and permanently recorded in [`audit_log.csv`](audit_log.csv).*

| Case ID | Category | Test Scenario | Decision & Rule Fired | Live Razorpay Payment Link Generated | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TC-01** | One-Off | Transient UPI Timeout (₹1,499) | `RETRY_LINK_NOW` (`RULE_HIGH_PROB_IMMEDIATE_RETRY`) | [https://rzp.io/rzp/WhPCYnG](https://rzp.io/rzp/WhPCYnG) | **PASS** |
| **TC-02** | One-Off | Card Gateway Technical Error (₹2,999) | `RETRY_LINK_NOW` (`RULE_HIGH_PROB_IMMEDIATE_RETRY`) | [https://rzp.io/rzp/4Szv8XS6](https://rzp.io/rzp/4Szv8XS6) | **PASS** |
| **TC-03** | One-Off | Insufficient Funds (₹799) | `RETRY_LINK_DELAYED` (`RULE_LOW_PROB_DELAYED_NUDGE`) | *N/A (Delayed Outreach)* | **PASS** |
| **TC-04** | One-Off | Expired Card (₹1,200) | `ESCALATE_HUMAN` (`RULE_HARD_DECLINE_COMPLIANCE`) | *N/A (Compliance Hold)* | **PASS** |
| **TC-05** | One-Off | Stolen Card Hard Decline (₹3,500) | `ESCALATE_HUMAN` (`RULE_HARD_DECLINE_COMPLIANCE`) | *N/A (0 Auto-Retries)* | **PASS** |
| **TC-06** | One-Off | Fraud Suspected (₹4,200) | `ESCALATE_HUMAN` (`RULE_HARD_DECLINE_COMPLIANCE`) | *N/A (Risk Team Hold)* | **PASS** |
| **TC-07** | One-Off | High Value Ceiling (₹28,500) | `ESCALATE_HUMAN` (`RULE_HIGH_AMOUNT_ESCALATION`) | *N/A (VIP Concierge)* | **PASS** |
| **TC-08** | One-Off | Duplicate Failure in Cooldown | `STOP` (`RULE_COOLDOWN_ACTIVE`) | *N/A (Duplicate Suppressed)* | **PASS** |
| **TC-09** | Subscription | 1st Mandate Failure - Transient (₹999/mo) | `SCHEDULE_RETRY_DAY_1` (`RULE_SUB_STAGE_1_RETRY`) | *N/A (Mandate T+24h)* | **PASS** |
| **TC-10** | Subscription | 2nd Mandate Failure - Low Funds (₹1,499/mo) | `SCHEDULE_RETRY_DAY_3` (`RULE_SUB_STAGE_2_LIQUIDITY_BUFFER`) | *N/A (Mandate T+3d)* | **PASS** |
| **TC-11** | Subscription | Expired Mandate Card | `SEND_UPDATE_PAYMENT_METHOD_LINK` (`RULE_SUB_INSTRUMENT_UPDATE_REQUIRED`) | [https://rzp.io/rzp/ZonMd4py](https://rzp.io/rzp/ZonMd4py) | **PASS** |
| **TC-12** | Subscription | 3+ Mandate Failures | `CANCEL_SUBSCRIPTION_STOP` (`RULE_SUB_MAX_RETRIES_EXCEEDED`) | *N/A (Auto-Billing Halted)* | **PASS** |

---

## 7. Failure Recovery & Debugging Log

A complete running record of real-world bugs hit during engineering and how they were resolved is documented in [`DEBUGGING_LOG.md`](DEBUGGING_LOG.md):
- **Windows `cp1252` Console Encoding:** Handled stdout Unicode glyph serialization issues by enforcing standard INR currency output.
- **Pickle Namespace Deserialization:** Resolved `__main__` namespace binding issues in `FunctionTransformer` by refactoring pure DataFrame feature prep.
- **Razorpay API Latency & Timeouts:** Implemented resilient 30-second client timeouts and per-scenario exception isolation.
- **In-Memory Cooldown Verification:** Designed automated 2-step test cases to deterministically verify active cooldown suppressions.
- **Audit Log Hash Chain Consistency:** Enforced strict string normalization in SHA-256 ledger computations across all serialized rows.

---

## 8. How to Run & Verify (Instructions for Judges)

### 1. Prerequisites
- Python 3.10+
- Razorpay Test Mode API Keys (configured in `.env`)

### 2. Setup Virtual Environment
```bash
# Clone the repository
git clone https://github.com/Parth-2701/Buildathon.git
cd Buildathon

# Create and activate virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run Automated Test Suite (29 Tests)
```bash
python run_tests.py
```

### 4. Run the 5,000-Transaction Comparative Benchmark
```bash
python evaluate.py
```

### 5. Run Live Test Mode Validation (12 Live Test Cases + Hash Chain Verification)
```bash
python run_live_validation.py
```

### 6. Start Webhook Server (Optional for Live Webhook Delivery)
```bash
uvicorn app:app --port 5000 --reload
```

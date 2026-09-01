# AI Revenue Recovery Agent

### Razorpay Buildathon — Track 3: Autonomous Agents & Workflows

An autonomous, compliance-first AI agent designed to diagnose failed Razorpay payments, enforce strict regulatory stopping rules, optimize retry timing using calibrated machine learning, and autonomously generate Test Mode Payment Links with an immutable audit trail.

---

## 1. Problem Chosen & Justification

- **Chosen Scope:** **Failed-Payment Revenue Recovery** (`payment.failed` $\rightarrow$ diagnose $\rightarrow$ bounded action $\rightarrow$ measured recovery via Razorpay Payment Links).
- **One-Line Justification:** *Failed payments cause immediate, high-intent revenue leakage that can be recovered automatically through intelligent diagnosis, whereas checkout abandonment or receivables collection involve ambiguous intent and third-party friction.*

---

## 2. Architecture & Decision Flow

```
Incoming Webhook (`payment.failed`)
        │
        ▼
┌─────────────────────────┐
│ 1. Webhook Receiver     │  FastAPI `/webhook` — Cryptographic HMAC-SHA256 verification
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ 2. Feature Builder      │  Extracts amount, error code, method, and in-memory history
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. Policy Engine: Deterministic Guardrails & ML Optimization                │
│                                                                             │
│  [RULE 1] Prior failures >= 2?                    ──► STOP                  │
│  [RULE 2] Action in last 6 hours (Cooldown)?      ──► STOP                  │
│  [RULE 3] Hard decline (stolen, blocked, fraud)?  ──► ESCALATE_HUMAN        │
│  [RULE 4] Amount > ₹10,000 threshold?             ──► ESCALATE_HUMAN        │
│                                                                             │
│  [ML LAYER] Calibrated Recovery Model P(Recovery | Features)                │
│             • P(Recovery) >= 0.40                 ──► RETRY_LINK_NOW        │
│             • P(Recovery) < 0.40                  ──► RETRY_LINK_DELAYED    │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            ▼                                                     ▼
┌─────────────────────────┐                             ┌──────────────────┐
│ 4. Action Executor      │                             │ 5. Audit Logger  │
│ Creates Razorpay Link   │                             │ Writes immutable │
│ (Test Mode API)         │                             │ CSV record       │
└─────────────────────────┘                             └──────────────────┘
```

---

## 3. Stopping Rules & Compliance Escalation Policy

This system enforces four deterministic guardrails that **cannot be overridden by machine learning**:

1. **Max Automated Attempts Ceiling:** Maximum **2 automated recovery attempts** per transaction or order ID. Beyond 2 attempts, the agent permanently halts (`STOP`) to protect customer goodwill.
2. **Mandatory 6-Hour Cooldown:** No duplicate recovery action is triggered within a 6-hour window (`RULE_COOLDOWN_ACTIVE`).
3. **Strict Zero-Tolerance Hard Declines:** Error codes indicating dead or compromised instruments (`stolen_card`, `card_lost_or_stolen`, `card_blocked`, `card_expired`, `fraud_suspected`, `risk_check_failed`, `bank_account_invalid`) are **strictly routed to human review (`ESCALATE_HUMAN`)** with **0 automated customer retries**.
4. **High-Ticket Risk Ceiling:** Any transaction exceeding **₹10,000** (`AMOUNT_ESCALATION_THRESHOLD`) automatically routes to human concierge support (`ESCALATE_HUMAN`) to eliminate large-value automated retry risk.

---

## 4. AI Judgment: Where ML is Used vs. Where Rules are Used

| Component | Technology | Rationale & Tradeoff |
| :--- | :--- | :--- |
| **Stopping Rules & Rate Limits** | Hard Rules | Safety and spam prevention must be 100% deterministic and predictable. |
| **Fraud & Stolen Card Handling** | Hard Rules | Regulatory compliance, card network rules, and chargeback prevention permit zero probabilistic error. |
| **High Amount Escalation** | Hard Rules | Financial exposure ceiling cannot rely on model confidence. |
| **Recovery Timing & Prioritization** | **Calibrated ML Model** (`HistGradientBoostingClassifier` + Isotonic Calibration) | Predicts recovery probability on soft failures based on monetary elasticity, error type, payment method, and prior attempt count. Optimizes between immediate links (`RETRY_LINK_NOW`) and delayed outreach (`RETRY_LINK_DELAYED`). |
| **Out-of-Distribution Fallback** | Safe Rule Defaults | If an unvetted error code or corrupted payload arrives, the system falls back to conservative [`ORACLE_PROBS`](constants.py) without failing. |

---

## 5. Synthetic Batch Benchmark Evaluation (N = 5,000)

*Evaluated across 5,000 synthetic failed transactions representing **₹1.23 Crore** in failed payments.*

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

## 6. Live Test Mode Demo Evidence

*Executed against live Razorpay Test Mode API and logged in [`audit_log.csv`](audit_log.csv).*

| Case ID | Test Scenario | Expected Decision | Actual Decision & Rule Fired | Live Razorpay Payment Link Generated | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TC-01** | Transient UPI Timeout (₹1,499) | `RETRY_LINK_NOW` | `RETRY_LINK_NOW` (`RULE_HIGH_PROB_IMMEDIATE_RETRY`) | [https://rzp.io/rzp/80bG6xL](https://rzp.io/rzp/80bG6xL) | **PASS** |
| **TC-02** | Card Gateway Error (₹2,999) | `RETRY_LINK_NOW` | `RETRY_LINK_NOW` (`RULE_HIGH_PROB_IMMEDIATE_RETRY`) | [https://rzp.io/rzp/mZ386Pbe](https://rzp.io/rzp/mZ386Pbe) | **PASS** |
| **TC-03** | Insufficient Funds (₹799) | `RETRY_LINK_DELAYED`| `RETRY_LINK_DELAYED` (`RULE_LOW_PROB_DELAYED_NUDGE`) | *N/A (Delayed Outreach)* | **PASS** |
| **TC-04** | Expired Card (₹1,200) | `ESCALATE_HUMAN` | `ESCALATE_HUMAN` (`RULE_HARD_DECLINE_COMPLIANCE`) | *N/A (Compliance Hold)* | **PASS** |
| **TC-05** | Stolen Card Hard Decline (₹3,500)| `ESCALATE_HUMAN` | `ESCALATE_HUMAN` (`RULE_HARD_DECLINE_COMPLIANCE`) | *N/A (0 Auto-Retries)* | **PASS** |
| **TC-06** | Fraud Suspected (₹4,200) | `ESCALATE_HUMAN` | `ESCALATE_HUMAN` (`RULE_HARD_DECLINE_COMPLIANCE`) | *N/A (Risk Team Review)* | **PASS** |
| **TC-07** | High Value Ceiling (₹28,500) | `ESCALATE_HUMAN` | `ESCALATE_HUMAN` (`RULE_HIGH_AMOUNT_ESCALATION`) | *N/A (Concierge Routing)* | **PASS** |
| **TC-08** | Duplicate Failure in Cooldown | `STOP` | `STOP` (`RULE_COOLDOWN_ACTIVE`) | *N/A (Duplicate Suppressed)* | **PASS** |

---

## 7. Failure Recovery & Debugging Log

A complete running record of real-world bugs hit during engineering and how they were resolved is documented in [`DEBUGGING_LOG.md`](DEBUGGING_LOG.md):
- **Windows `cp1252` Console Encoding:** Handled stdout Unicode glyph serialization issues by enforcing standard INR currency output.
- **Pickle Namespace Deserialization:** Resolved `__main__` namespace binding issues in `FunctionTransformer` by refactoring pure DataFrame feature prep.
- **Razorpay API Latency & Timeouts:** Implemented resilient 30-second client timeouts and per-scenario exception isolation.
- **In-Memory Cooldown Verification:** Designed automated 2-step test cases to deterministically verify active cooldown suppressions.

---

## 8. How to Run & Verify (Instructions for Judges)

### 1. Prerequisites
- Python 3.10+
- Razorpay Test Mode API Keys (configured in `.env`)

### 2. Setup Virtual Environment
```bash
# Clone the repository
git clone https://github.com/Parth-2701/razorpay-buildathon.git
cd razorpay-buildathon

# Create and activate virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run Automated Test Suite (26 Tests)
```bash
python run_tests.py
```

### 4. Run the 5,000-Transaction Comparative Benchmark
```bash
python evaluate.py
```

### 5. Run Live Test Mode Validation
```bash
python run_live_validation.py
```

### 6. Start Webhook Server (Optional for Live Webhook Delivery)
```bash
uvicorn app:app --port 5000 --reload
```

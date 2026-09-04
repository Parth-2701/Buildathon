# AI Revenue Recovery Agent

### Razorpay Buildathon — Track 3: Autonomous Agents & Workflows
**Repository:** [https://github.com/Parth-2701/Buildathon.git](https://github.com/Parth-2701/Buildathon.git)

An autonomous, compliance-first AI revenue recovery platform designed to eliminate revenue leaks across the entire transaction lifecycle:
1. **One-Off Payment Failures & Subscription Mandates:** Real-time webhook ingestion, calibrated ML recovery probability, and NPCI-compliant retry sequencing.
2. **Checkout Abandonment Recovery:** Drop-off step intent scoring, automated payment link generation, and spam-prevention ceilings.
3. **B2B Receivables Chaser & Promise-to-Pay Tracker:** Multi-stage dunning ladder (Day+3 Friendly $\rightarrow$ Day+10 Itemized $\rightarrow$ Day+21 Final Notice $\rightarrow$ Day+30 Collections), promise-to-pay hold, and broken-promise acceleration.
4. **Actionable Human Escalation Triage:** Operational queue and REST endpoints for compliance holds and high-ticket exceptions.
5. **Tamper-Evident Audit Ledger:** Cryptographic SHA-256 row-by-row hash chain securing every agent action and state transition.

---

## 1. The 3 Revenue Leakage Pillars

| Pillar | Trigger / Surface | Autonomous Agent Strategy | Hard Stopping Rule / Guardrail |
| :--- | :--- | :--- | :--- |
| **Pillar 1: Failed Payments & Subscriptions** | `payment.failed`, `subscription.charged.failed` | Calibrated ML predicts soft decline recovery. Instant Razorpay link for transient UPI/card errors. Staged mandate retry (Day 1 $\rightarrow$ 3 $\rightarrow$ 7). | Max 2 one-off retries / 3 mandate retries; 6h cooldown; zero-tolerance hard compliance declines (`stolen_card`, `fraud`); ₹10,000 ceiling. |
| **Pillar 2: Checkout Abandonment** | Inactivity $>15$ mins on checkout sessions | Intent scoring based on cart step (`payment_method`, `otp` vs `cart`); generates live Razorpay links with personalized copy. | Max 2 nudges per session; 2-hour cooldown; automatic suppression for low-intent carts ($< ₹500$); auto-stop on `order.paid`. |
| **Pillar 3: B2B Receivables & Invoices** | Overdue B2B invoices past due date | 4-stage dunning ladder (Friendly Nudge $\rightarrow$ Itemized Notice $\rightarrow$ Final Notice $\rightarrow$ Collections Escalation). | Active Promise-to-Pay pauses dunning; $\ge 2$ broken promises routes immediately to human specialist; ₹50,000 high-ticket ceiling. |

---

## 2. Architecture & Decision Flow

```
   Incoming Webhooks / Cron Sweepers (Payments, Abandoned Carts, Overdue Invoices)
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ 1. SQLite WAL Persistence & Webhook Idempotency Layer                                   │
│    • Cryptographic HMAC-SHA256 signature verification                                  │
│    • Durable SQLite tables (`transaction_state`, `processed_events`, `checkout_sessions`) │
│    • Process crashes & restarts preserve cooldowns and failure counters                 │
└───────────────────────────────────────┬─────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ 2. Deterministic Compliance & Stopping Guardrails (Tier 1)                             │
│    • Hard declines (stolen card, fraud, blocked)?       ──► ESCALATE_HUMAN (Triage)     │
│    • High financial exposure (> ₹10k txn / > ₹50k inv)? ──► ESCALATE_HUMAN (Triage)     │
│    • Retry ceiling reached / Cooldown active?           ──► STOP (Outreach suppressed)  │
│    • Active Promise-to-Pay on file?                     ──► STOP (Dunning paused)       │
└───────────────────────────────────────┬─────────────────────────────────────────────────┘
                                        │ (Passed Safety Guardrails)
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ 3. Calibrated ML Probability Model & Multi-Stage State Machines (Tier 2)                │
│    • HistGradientBoostingClassifier + Isotonic Probability Calibration                  │
│    • Soft declines: P(Recovery) >= 0.40 ──► RETRY_LINK_NOW | < 0.40 ──► RETRY_DELAYED   │
│    • Mandates: Stage 1 (T+24h) ──► Stage 2 (T+3d) ──► Stage 3 (T+7d)                    │
│    • B2B Invoices: Day+3 (Friendly) ──► Day+10 (Itemized) ──► Day+21 (Final Notice)     │
└───────────────────────────────────────┬─────────────────────────────────────────────────┘
                                        │
             ┌──────────────────────────┼──────────────────────────┐
             ▼                          ▼                          ▼
┌────────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│ 4. Action Executor     │  │ 5. Read-Only LLM       │  │ 6. Cryptographic       │
│ Live Razorpay Test API:│  │ Root-cause diagnostics │  │    Audit Ledger        │
│ Generates instant      │  │ and personalized       │  │ SHA-256 hash-chained   │
│ recovery payment links │  │ customer copy; never   │  │ row-by-row audit trail │
│ (`https://rzp.io/...`) │  │ decides actions        │  │ in `audit_log.csv`     │
└────────────────────────┘  └────────────────────────┘  └────────────────────────┘
```

### 2.1 Resilient Tiered Link Generation & Sandbox Quota Handling
To prevent demo disruptions from Razorpay's Test Mode sandbox quota (which caps standard `payment_links` at 30 per unactivated account), [`executor.py`](executor.py) implements an intelligent 3-tier execution strategy:
1. **Tier 1 (Direct Payment Link):** Attempts `_client.payment_link.create()` first for native `https://rzp.io/...` links.
2. **Tier 2 (Real Razorpay-Hosted Link via Invoices API):** If Razorpay returns `limit of 30 reached`, it immediately generates an official Razorpay-hosted link via `_client.invoice.create({'type': 'invoice', ...})`, producing an active, unexpired `https://rzp.io/...` payment page with zero quota constraints.
3. **Tier 3 (Interactive Checkout Modal):** Fallback interactive checkout page at `http://localhost:5000/pay/{order_id}` powered by official `checkout.js`, allowing full live payment simulations.

---

## 3. AI Judgment: Strict Separation of Concerns

| Component | Technology | Architectural Boundary & Rationale |
| :--- | :--- | :--- |
| **Stopping Rules & Rate Limits** | Hard Deterministic Rules | Safety, compliance, spam prevention, and cooldowns must be 100% deterministic and predictable. |
| **Fraud & Stolen Instrument Handling** | Hard Deterministic Rules | Regulatory compliance, card network rules, and chargeback prevention permit zero probabilistic error. |
| **High Amount Escalation** | Hard Deterministic Rules | Financial exposure ceilings cannot rely on model confidence. |
| **Recovery Probability & Timing** | **Calibrated ML Model** (`HistGradientBoosting` + Isotonic) | Evaluates non-linear interactions (amount elasticity, error code, payment method, retry decay) to classify recovery likelihood on soft declines. |
| **Action Execution & Link Dispatch** | **Tiered Razorpay Dispatcher** (`executor.py`) | Tries native Razorpay Payment Links first; automatically fails over to real hosted `rzp.io` Invoice links on sandbox quota exhaustion to guarantee live, testable links. |
| **Root-Cause Diagnosis & Customer Copy** | **LLM Diagnostics Layer** (`llm_diagnostics.py`) | **Strictly read-only & explanatory.** The LLM *never* selects an action, never alters amounts, and never moves money. It produces natural language internal explanations and personalized customer messaging. |
| **Actionable Human Triage** | **SQLite Queue + REST API** (`escalation.py`) | Persists escalated items in SQLite with full context, supports outbound notifications (Slack), and exposes operator resolution endpoints. |
| **Tamper-Evident Audit Ledger** | **Cryptographic Hash Chain** (`SHA-256`) | Every audit entry is cryptographically linked to the previous row's hash (`entry_hash = SHA256(prev_hash + row_data)`), making retroactive tampering mathematically impossible. |

---

## 4. Modeled Expected-Value Comparison (Synthetic)

*Evaluated across 6,500 total events representing **₹1.65 Crore** in at-risk revenue across all three pillars.*

| Track / Metric | 🔴 Naive Industry Baseline | 🟢 AI Recovery Agent | 🚀 Measured Impact / Uplift |
| :--- | :--- | :--- | :--- |
| **T1: Failed Payments (N=5,000)** | ₹2,478,472.86 *(Blind 24h Retry)* | **₹4,171,440.23** *(Rules + Calibrated ML)* | **+₹1,692,967.37 (+68.31%)** |
| ↳ *Customer Spam (Messages)* | 5,000 messages | **3,735 messages** | **-25.3% spam reduced** |
| ↳ *Compliance Violations Prevented* | 1,133 violations | **0 (Strictly 0%)** | **1,133 regulatory hazards prevented** |
| **T2: Checkout Abandonment (N=1,000)**| ₹159,474.04 *(Blind Spam)* | **₹345,308.78** *(Intent-Weighted)* | **+₹185,834.74 (+116.53%)** |
| ↳ *Cart Spam Suppressed* | 1,000 messages | **857 messages** | **-14.3% cart spam reduced** |
| **T3: B2B Receivables (N=500)** | ₹4,091,687.27 *(Static Day 30 Notice)* | **₹8,446,767.84** *(4-Stage Ladder + PTP)* | **+₹4,355,080.57 (+106.44%)** |
| **TOTAL REVENUE RECOVERED** | **₹6,729,634.17** | **₹12,963,516.85** | **+₹6,233,882.68 (+92.63% Total Uplift)** |

> [!NOTE]
> **Methodology Disclaimer:** This evaluation uses domain-grounded synthetic transaction distributions with calibrated recovery probability models. It measures relative expected value under identical simulated conditions, not a production A/B test. Live API correctness is separately verified below via `run_live_validation.py` across 18 real Razorpay Test Mode cases.

### Model Calibration Metrics
- **Algorithm:** `HistGradientBoostingClassifier` with `CalibratedClassifierCV` (Isotonic Regression)
- **ROC-AUC Score:** **`0.7574`** *(80/20 train/test split)*
- **Brier Score Loss:** **`0.1921`** *(True probabilistic alignment)*

---

## 5. Live Test Mode Demo Evidence (18 Verified Cases)

*Executed against live Razorpay Test Mode API endpoints and permanently recorded in the cryptographic [`audit_log.csv`](audit_log.csv).*

| Case ID | Track | Test Scenario | Decision & Rule Triggered | Live Razorpay Payment Link Generated | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TC-01** | Payments | Transient UPI Timeout (₹1,499) | `RETRY_LINK_NOW` (`RULE_HIGH_PROB_IMMEDIATE_RETRY`) | Live Razorpay URL Dispatched | **PASS** |
| **TC-02** | Payments | Card Gateway Technical Error (₹2,999) | `RETRY_LINK_NOW` (`RULE_HIGH_PROB_IMMEDIATE_RETRY`) | Live Razorpay URL Dispatched | **PASS** |
| **TC-03** | Payments | Insufficient Funds (₹799) | `RETRY_LINK_DELAYED` (`RULE_LOW_PROB_DELAYED_NUDGE`) | *N/A (Delayed Outreach)* | **PASS** |
| **TC-04** | Payments | Expired Card Instrument (₹1,200) | `ESCALATE_HUMAN` (`RULE_HARD_DECLINE_COMPLIANCE`) | *N/A (Triage Queue)* | **PASS** |
| **TC-05** | Payments | Compliance Hard Decline - Stolen Card (₹3,500) | `ESCALATE_HUMAN` (`RULE_HARD_DECLINE_COMPLIANCE`) | *N/A (0 Auto-Retries)* | **PASS** |
| **TC-06** | Payments | Compliance Hard Decline - Fraud Suspected (₹4,200) | `ESCALATE_HUMAN` (`RULE_HARD_DECLINE_COMPLIANCE`) | *N/A (Risk Hold)* | **PASS** |
| **TC-07** | Payments | High Value Risk Ceiling (₹28,500) | `ESCALATE_HUMAN` (`RULE_HIGH_AMOUNT_ESCALATION`) | *N/A (VIP Concierge)* | **PASS** |
| **TC-08** | Payments | Duplicate Failure in Cooldown | `STOP` (`RULE_COOLDOWN_ACTIVE`) | *N/A (Spam Suppressed)* | **PASS** |
| **TC-09** | Subscriptions | 1st Mandate Failure - Transient (₹999/mo) | `SCHEDULE_RETRY_DAY_1` (`RULE_SUB_STAGE_1_RETRY`) | *N/A (Mandate T+24h)* | **PASS** |
| **TC-10** | Subscriptions | 2nd Mandate Failure - Low Funds (₹1,499/mo) | `SCHEDULE_RETRY_DAY_3` (`RULE_SUB_STAGE_2_LIQUIDITY_BUFFER`) | *N/A (Mandate T+3d)* | **PASS** |
| **TC-11** | Subscriptions | Expired Mandate Card | `SEND_UPDATE_PAYMENT_METHOD_LINK` (`RULE_SUB_INSTRUMENT_UPDATE_REQUIRED`) | Live Razorpay URL Dispatched | **PASS** |
| **TC-12** | Subscriptions | 3+ Mandate Failures | `CANCEL_SUBSCRIPTION_STOP` (`RULE_SUB_MAX_RETRIES_EXCEEDED`) | *N/A (Auto-Billing Halted)* | **PASS** |
| **TC-13** | Abandonment | High-Intent Drop-off at OTP Friction (₹3,499) | `NUDGE_NOW` (`RULE_ABANDON_HIGH_INTENT_STAGE1`) | Live Razorpay URL Dispatched | **PASS** |
| **TC-14** | Abandonment | Low-Intent Window Shopping ($< ₹500$) | `STOP` (`RULE_ABANDON_LOW_INTENT`) | *N/A (Spam Suppressed)* | **PASS** |
| **TC-15** | Abandonment | `order.paid` Webhook Clears Cart Session | `STOP` (`RULE_ABANDON_ALREADY_COMPLETED`) | *N/A (Outreach Cleared)* | **PASS** |
| **TC-16** | Receivables | Overdue Invoice Day+3 Friendly Nudge (₹18,500) | `REMINDER_1` (`RULE_REC_STAGE1_FRIENDLY`) | Live Razorpay URL Dispatched | **PASS** |
| **TC-17** | Receivables | Promise-to-Pay Active Hold | `STOP` (`RULE_REC_PROMISE_ACTIVE`) | *N/A (Dunning Paused)* | **PASS** |
| **TC-18** | Triage | Operator Resolves Queued Ticket with Audit Log | `ESCALATION_RESOLVED` (`MANUAL_OPERATOR_RESOLUTION`) | *N/A (Audited)* | **PASS** |

---

## 6. API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/health` | `GET` | Health check and enabled agent capabilities |
| `/pay/{order_id}` | `GET` | Interactive Razorpay Checkout modal page powered by real Razorpay Orders (`checkout.js`), ensuring test payments can be simulated live in browser |
| `/webhook` | `POST` | Ingests Razorpay webhooks (`payment.failed`, `subscription.charged.failed`, `order.paid`) with HMAC signature verification and SQLite idempotency |
| `/escalations` | `GET` | Lists queued human escalations (filterable by `?status=open` or `resolved`) |
| `/escalations/{id}/resolve` | `POST` | Resolves an escalation ticket with operator notes and appends to the hash-chained audit log |
| `/checkout/session` | `POST` | Registers or updates an active checkout cart session |
| `/checkout/sweep` | `POST` | Triggers on-demand sweeper for abandoned checkout carts past the cutoff window |
| `/invoices` | `POST` | Creates or syncs an overdue B2B invoice |
| `/invoices/{id}` | `GET` | Inspects invoice status, dunning stage, and promise details |
| `/invoices/{id}/promise` | `POST` | Registers a customer Promise-to-Pay date, pausing automated dunning |
| `/invoices/{id}/pay` | `POST` | Marks an invoice as paid in full, terminating dunning sequences |
| `/invoices/sweep` | `POST` | Triggers on-demand dunning sweep across active overdue invoices |

---

## 7. How to Run & Verify (Instructions for Judges)

### 1. Prerequisites
- Python 3.10+
- Razorpay Test Mode API Keys (configured in `.env`)

### 2. Setup Environment
```bash
git clone https://github.com/Parth-2701/Buildathon.git
cd Buildathon

python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Run Automated Test Suite (63 Tests)
```bash
python run_tests.py
```

### 4. Run Multi-Track Comparative Benchmark
```bash
python evaluate.py
```

### 5. Run Live Test Mode Validation (18 Live Cases + Hash Chain Verification)
```bash
python run_live_validation.py
```

### 6. Start Webhook Server (Optional for Live Webhook Delivery)
```bash
uvicorn app:app --port 5000 --reload
```

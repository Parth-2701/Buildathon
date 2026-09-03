"""
llm_diagnostics.py - LLM-powered root-cause diagnosis and personalized customer copy.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent

Architectural Boundary:
The LLM is strictly read-only and explanatory. It NEVER decides an action,
modifies financial amounts, or triggers money movement. It only explains
decisions already made deterministically by the policy engine and personalizes customer copy.
"""

import os
import json
import logging
import urllib.request
from typing import Dict, Any, Optional

logger = logging.getLogger("recovery_agent.llm")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def _generate_fallback_diagnosis_and_copy(
    features: Dict[str, Any],
    action: str,
    rule: str,
    prob: float,
) -> Dict[str, str]:
    """
    Deterministic rule-guided diagnostic & copywriting engine.
    Ensures zero external dependency and 100% test reliability.
    """
    error_code = features.get("error_code", "unknown")
    amount_inr = features.get("amount_inr", 0.0)
    method = (features.get("method") or "payment instrument").upper()
    prior = features.get("prior_failures", 0)

    # 1. Generate internal audit diagnosis
    if rule == "RULE_HARD_DECLINE_COMPLIANCE":
        diagnosis = (
            f"Regulatory & compliance safety block: '{error_code}' indicates an invalid or compromised {method}. "
            f"Automated outreach suppressed (0% recovery probability); routed to risk operations."
        )
        customer_msg = (
            f"Your recent transaction of INR {amount_inr:,.2f} could not be completed because the issuing institution declined the {method}. "
            f"Please contact your bank or try an alternate payment method."
        )
    elif rule == "RULE_HIGH_AMOUNT_ESCALATION":
        diagnosis = (
            f"High-exposure threshold trigger: Order value (INR {amount_inr:,.2f}) exceeds the INR 10,000 auto-recovery ceiling. "
            f"Escalated to human VIP concierge team to prevent unmonitored automated retries."
        )
        customer_msg = (
            f"Thank you for your order of INR {amount_inr:,.2f}. Our support team is reviewing your transaction and will assist you shortly."
        )
    elif rule == "RULE_MAX_RETRIES_EXCEEDED":
        diagnosis = (
            f"Stopping rule enforced: Transaction reached {prior} prior attempts (max limit = 2). "
            f"Recovery permanently stopped to prevent customer fatigue and spam."
        )
        customer_msg = (
            f"We noticed multiple unsuccessful attempts for your payment of INR {amount_inr:,.2f}. "
            f"To prevent duplicate charges, no further automated attempts will be made. Please reach out if you need assistance."
        )
    elif rule == "RULE_COOLDOWN_ACTIVE":
        diagnosis = (
            f"Rate-limiting guardrail: Webhook received within active 6-hour cooldown window. "
            f"Duplicate action suppressed to ensure strictly bounded customer communication."
        )
        customer_msg = ""
    elif action == "RETRY_LINK_NOW":
        diagnosis = (
            f"High-intent transient failure ({error_code}) on {method} with estimated {prob:.0%} recovery likelihood. "
            f"Immediate Razorpay payment link dispatched to capture active user session."
        )
        customer_msg = (
            f"We noticed your {method} payment of INR {amount_inr:,.2f} timed out due to temporary bank gateway latency. "
            f"Your order is reserved — click your secure Razorpay link to complete payment in 1 click."
        )
    elif action == "RETRY_LINK_DELAYED":
        diagnosis = (
            f"Soft failure ({error_code}) on {method} with moderate recovery probability ({prob:.0%}). "
            f"Delayed nudge queued to allow customer time to replenish funds/switch payment methods."
        )
        customer_msg = (
            f"Your payment of INR {amount_inr:,.2f} could not be processed. "
            f"You can easily complete your purchase anytime using our secure Razorpay link with UPI, Cards, or Netbanking."
        )
    else:
        diagnosis = f"Policy action {action} triggered via {rule} for {error_code} on INR {amount_inr:,.2f}."
        customer_msg = f"Complete your payment of INR {amount_inr:,.2f} via Razorpay."

    return {
        "diagnosis_text": diagnosis,
        "customer_message": customer_msg,
    }


def _call_gemini_api(prompt: str, api_key: str) -> Optional[str]:
    """Invokes Google Gemini API via lightweight HTTP POST."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 200},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            return text
    except Exception as e:
        logger.warning("Gemini API call failed (%s). Using fallback engine.", e)
        return None


def generate_diagnosis_and_copy(
    features: Dict[str, Any],
    action: str,
    rule: str,
    recovery_prob: float,
) -> Dict[str, str]:
    """
    Generates a one-sentence internal diagnostic explanation and personalized customer copy.
    
    Returns:
        Dict with "diagnosis_text" and "customer_message".
    """
    # If live Gemini API key is configured, generate dynamic LLM output
    if GEMINI_API_KEY:
        prompt = (
            f"You are a payment operations AI diagnostics assistant. "
            f"A payment failed with error_code='{features.get('error_code')}', amount=INR {features.get('amount_inr')}, "
            f"method='{features.get('method')}', prior_failures={features.get('prior_failures')}. "
            f"The deterministic policy engine chose action='{action}' via rule='{rule}' (model prob={recovery_prob:.2f}).\n"
            f"Output a valid JSON object with exactly two keys:\n"
            f"1. 'diagnosis_text': A concise, professional one-sentence internal audit note explaining the root cause.\n"
            f"2. 'customer_message': A polite, clear, 1-sentence customer outreach message.\n"
            f"Output JSON ONLY:"
        )
        llm_resp = _call_gemini_api(prompt, GEMINI_API_KEY)
        if llm_resp:
            try:
                # Clean code blocks if present
                clean_json = llm_resp.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(clean_json)
                if "diagnosis_text" in parsed and "customer_message" in parsed:
                    return {
                        "diagnosis_text": parsed["diagnosis_text"].strip(),
                        "customer_message": parsed["customer_message"].strip(),
                    }
            except Exception as e:
                logger.warning("Failed to parse Gemini JSON output (%s). Falling back.", e)

    # Built-in robust diagnostic engine
    return _generate_fallback_diagnosis_and_copy(features, action, rule, recovery_prob)

"""Detect the intent of a customer email.

Offline: weighted keyword rules (transparent and easy to tune per client).
AI mode: the LLM returns JSON {"intent", "confidence"}; if that fails, the rules are used.
"""

import json
import re

from . import llm

INTENTS = ["order_status", "refund", "booking", "complaint", "other"]
LABELS = {"order_status": "Order status", "refund": "Refund / return", "booking": "Booking",
          "complaint": "Complaint", "other": "Other"}

# (pattern, weight). Subject matches count double.
RULES = {
    "order_status": [(r"where is my order", 3), (r"\btracking\b", 3), (r"\bshipp?(ed|ing)?\b", 2),
                     (r"\bdeliver(y|ed)?\b", 1), (r"\bprocessing\b", 1), (r"\bdispatch", 2), (r"\barriv(e|al)\b", 1)],
    "refund": [(r"\brefund", 3), (r"\breturn(ing)?\b", 2), (r"money back", 3), (r"\breimburse", 3),
               (r"\bexchange\b", 1), (r"\bcancel(led)?\b", 1)],
    "booking": [(r"\bbook(ing)?\b", 3), (r"\breserv(e|ation)", 3), (r"\bworkshop\b", 2), (r"\bplaces?\b", 1),
                (r"\bspaces?\b", 1), (r"\bappointment\b", 2), (r"\bavailab", 1)],
    "complaint": [(r"\bdisappoint", 3), (r"\bunacceptable\b", 3), (r"\bbroken\b", 2), (r"\bdamaged?\b", 2),
                  (r"\bsmashed\b", 2), (r"\bcracked\b", 2), (r"\bterrible\b", 3), (r"\bcomplain", 3),
                  (r"second time", 2), (r"\bawful\b", 3)],
}
MIN_SCORE = 2      # below this the email is "other"
STRONG_SCORE = 12  # this much evidence counts as a strong signal


def classify_rules(subject, body):
    """Return (intent, confidence 0..1, scores) using keyword rules."""
    subject, body = subject.lower(), body.lower()
    scores = {}
    for intent, rules in RULES.items():
        score = 0
        for pattern, weight in rules:
            if re.search(pattern, subject):
                score += weight * 2
            if re.search(pattern, body):
                score += weight
        scores[intent] = score
    best = max(scores, key=scores.get)
    total = sum(scores.values())
    if scores[best] < MIN_SCORE:
        return "other", 0.5, scores  # no clear signal: low confidence so a human checks it
    # Confidence grows with (a) how much of the evidence points at the winner and
    # (b) how much evidence there is in absolute terms. Capped at 0.95: rules are never certain.
    share = scores[best] / total
    strength = min(1.0, scores[best] / STRONG_SCORE)
    confidence = round(min(0.95, 0.25 + 0.45 * share + 0.25 * strength), 2)
    return best, confidence, scores


CLASSIFY_PROMPT = (
    "Classify the customer email into exactly one intent: order_status, refund, booking, complaint, other. "
    'Reply with JSON only: {"intent": "...", "confidence": 0.0-1.0}. '
    "If the customer is upset AND asks for money back, choose refund."
)


def classify(subject, body, use_llm):
    """Return dict {intent, label, confidence, method}."""
    if use_llm:
        try:
            reply = llm.generate(CLASSIFY_PROMPT, f"Subject: {subject}\n\n{body}", temperature=0)
            data = json.loads(re.search(r"\{.*\}", reply, re.S).group())
            intent = data["intent"] if data.get("intent") in INTENTS else "other"
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
            return {"intent": intent, "label": LABELS[intent], "confidence": round(confidence, 2), "method": "ai"}
        except (RuntimeError, AttributeError, ValueError, KeyError, TypeError):
            pass  # fall back to the rules below
    intent, confidence, _ = classify_rules(subject, body)
    return {"intent": intent, "label": LABELS[intent], "confidence": confidence, "method": "rules"}

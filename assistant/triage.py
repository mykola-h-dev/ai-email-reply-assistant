"""Thread summary, priority (urgent / normal / low) and suggested labels.

AI mode: one LLM call returns JSON; anything invalid falls back to the rules.
Offline: an extractive one-line summary plus transparent keyword rules.
"""

import json
import re

from . import llm

PRIORITIES = ["urgent", "normal", "low"]
URGENT_PATTERNS = [r"\bunacceptable\b", r"\burgent(ly)?\b", r"\basap\b", r"\bimmediately\b",
                   r"\bchargeback\b", r"\bsolicitor\b", r"\blawyer\b", r"\blegal\b", r"second time",
                   r"\bby (today|tomorrow|friday|monday)\b", r"\bstill (no|not)\b"]
LOW_PATTERNS = [r"\bno rush\b", r"\bwhenever\b", r"\bno hurry\b", r"\bjust wondering\b", r"\bat your convenience\b"]
LABEL_PATTERNS = {
    "Damaged item": r"\b(damaged?|broken|smashed|cracked|chipped|faulty)\b",
    "Shipping": r"\b(tracking|dispatch\w*|shipp?\w*|deliver\w*)\b",
    "Payment": r"\b(pay|payment|refund\w*|money back|reimburse\w*)\b",
    "Sales lead": r"\b(wholesale|bulk|trade prices?|units)\b",
    "Workshop": r"\b(workshop|class)\b",
}
INTENT_LABELS = {"order_status": "Order status", "refund": "Refund", "booking": "Booking",
                 "complaint": "Complaint", "other": "General"}
GREETING_RE = re.compile(r"^(hi|hello|hey|dear|good (morning|afternoon))\b[^.!?]{0,40}?[,!.:]?\s*", re.I)
SIGNOFF_RE = re.compile(r"^(thanks|thank you|many thanks|best|kind regards|regards|cheers|best wishes)\b", re.I)


def _content_lines(body):
    """Body lines without the greeting, sign-off and the sender's name."""
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    kept = []
    for line in lines:
        if SIGNOFF_RE.match(line):
            break  # everything after "Thanks," / "Best," is the signature
        if not kept and GREETING_RE.match(line) and line.endswith(",") and len(line.split()) <= 6:
            continue  # "Hello Bramble & Co team,"
        line = GREETING_RE.sub("", line, count=1) if not kept else line
        if line and len(line.split()) > 2:
            kept.append(line)
    return kept


def summarize(subject, body, max_chars=160):
    """Extractive summary: the first meaningful sentence(s) of the email (greeting and signature skipped)."""
    text = " ".join(_content_lines(body))
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    sentences = [re.sub(r"\s+(cheers|thanks),?\s+\w+$", "", s, flags=re.I) for s in sentences]
    if not sentences:
        return subject
    summary = sentences[0]
    if len(summary.split()) < 9 and len(sentences) > 1:
        summary = f"{summary} {sentences[1]}"
    summary = summary[0].upper() + summary[1:]
    if len(summary) > max_chars:
        summary = summary[: max_chars - 3].rsplit(" ", 1)[0] + "..."
    return summary


def priority_rules(subject, body, intent):
    text = f"{subject}\n{body}".lower()
    if any(re.search(p, text) for p in URGENT_PATTERNS):
        return "urgent"
    if any(re.search(p, text) for p in LOW_PATTERNS):
        return "low"
    return "normal"


def labels_rules(subject, body, intent):
    text = f"{subject}\n{body}".lower()
    labels = [INTENT_LABELS.get(intent, "General")]
    labels += [name for name, pattern in LABEL_PATTERNS.items() if re.search(pattern, text)]
    return list(dict.fromkeys(labels))


def triage_rules(subject, body, intent):
    return {"summary": summarize(subject, body), "priority": priority_rules(subject, body, intent),
            "labels": labels_rules(subject, body, intent), "triaged_by": "rules"}


TRIAGE_PROMPT = (
    "You triage customer emails for a small shop. Reply with JSON only: "
    '{"summary": "one sentence, max 25 words", "priority": "urgent|normal|low", '
    '"labels": ["1-4 short labels"]}. urgent = angry, legal/chargeback threat, repeat problem or a deadline; '
    "low = explicitly no rush or purely informational."
)


def triage(subject, body, intent, use_llm):
    """Return {summary, priority, labels, triaged_by}."""
    if use_llm:
        try:
            reply = llm.generate(TRIAGE_PROMPT, f"Intent: {intent}\nSubject: {subject}\n\n{body}", temperature=0)
            data = json.loads(re.search(r"\{.*\}", reply, re.S).group())
            priority = data.get("priority") if data.get("priority") in PRIORITIES else None
            labels = [str(x)[:30] for x in data.get("labels", []) if str(x).strip()][:4]
            summary = str(data.get("summary", "")).strip()[:200]
            if priority and summary:
                return {"summary": summary, "priority": priority, "labels": labels or [INTENT_LABELS[intent]],
                        "triaged_by": "ai"}
        except (RuntimeError, AttributeError, ValueError, KeyError, TypeError):
            pass
    return triage_rules(subject, body, intent)

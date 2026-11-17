"""Draft a reply for each email: template filling (offline) or LLM rewrite (AI mode).

Drafts are suggestions for a human to review. Anything the assistant cannot
know (live order status, stock, availability) is left as a [CHECK: ...] note.
"""

import json
import re
from string import Template

from . import llm

ORDER_RE = re.compile(r"\b([A-Z]{2,4}-\d{4,6})\b")
MISSING_ORDER = "[order number - please confirm]"
NO_FAQ_ANSWER = ("I've passed your question to the right person on our team and we'll get back to you "
                 "within one working day.")


def load_company(templates_dir):
    return json.loads((templates_dir / "company.json").read_text(encoding="utf-8"))


def load_template(templates_dir, intent):
    return Template((templates_dir / f"{intent}.txt").read_text(encoding="utf-8"))


def extract_fields(incoming):
    """Pull the details templates need from the email."""
    first_name = incoming.sender_name.split()[0].strip("\"'") if incoming.sender_name else "there"
    match = ORDER_RE.search(f"{incoming.subject}\n{incoming.body}")
    return {"first_name": first_name.capitalize(), "order_number": match.group(1) if match else MISSING_ORDER}


def template_draft(incoming, intent, templates_dir, company, faq_hits=()):
    """Fill the intent's template. $faq_answer (used by the general template) takes the best FAQ match."""
    faq_answer = faq_hits[0][1].answer if faq_hits else NO_FAQ_ANSWER
    fields = {**extract_fields(incoming), "signature": company["signature"], "company": company["company"],
              "faq_answer": faq_answer}
    text = load_template(templates_dir, intent).safe_substitute(fields)
    if fields["order_number"] == MISSING_ORDER:
        text = text.replace(f"order {MISSING_ORDER}", "your order")  # read naturally when no number was given
    return text


AI_SYSTEM = (
    "You draft email replies for {company}'s customer service team. A human will review every draft. "
    "Write a warm, concise reply (under 150 words) in plain text. Use ONLY these company facts and "
    "FAQ entries:\n{facts}\n"
    "Never promise anything not in the facts. Where you would need live data (order status, tracking, "
    "availability, refund confirmation), insert a note like [CHECK: ...] for the reviewer. "
    "Follow the structure of the template. End with this signature exactly:\n{signature}"
)


def ai_draft(incoming, intent, templates_dir, company, faq_hits=()):
    base = template_draft(incoming, intent, templates_dir, company, faq_hits)
    facts = [f"- {f}" for f in company["facts"]]
    facts += [f"- [{entry.id}] {entry.question} {entry.answer}" for _, entry in faq_hits]
    system = AI_SYSTEM.format(company=company["company"], facts="\n".join(facts), signature=company["signature"])
    prompt = (f"Detected intent: {intent}\n\nCustomer email\nFrom: {incoming.sender_name}\n"
              f"Subject: {incoming.subject}\n\n{incoming.body}\n\nTemplate reply to adapt:\n{base}")
    return llm.generate(system, prompt, temperature=0.3)


def draft_reply(incoming, intent, templates_dir, company, use_llm, faq_hits=()):
    """Return (draft_text, method). faq_hits = [(score, knowledge.Entry)] used as grounding."""
    if use_llm:
        try:
            return ai_draft(incoming, intent, templates_dir, company, faq_hits), "ai"
        except RuntimeError:
            pass
    return template_draft(incoming, intent, templates_dir, company, faq_hits), "template"

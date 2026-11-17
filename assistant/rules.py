"""Business rules from a JSON file, applied after classification and triage.

Each rule: {"name", "when": {...conditions, all must match}, "then": {...actions}}.
Conditions: intent_in, keywords_any, amount_over, sender_domain_in, priority_in.
Actions: priority, add_labels, escalate_to, note.
"""

import json
import re

AMOUNT_RE = re.compile(r"(?:[$£€]\s?(\d[\d,]*(?:\.\d{1,2})?))|(?:(\d[\d,]*(?:\.\d{1,2})?)\s?(?:usd|gbp|eur|dollars|pounds|euros)\b)", re.I)
KNOWN_CONDITIONS = {"intent_in", "keywords_any", "amount_over", "sender_domain_in", "priority_in"}
KNOWN_ACTIONS = {"priority", "add_labels", "escalate_to", "note"}


def load_rules(path):
    if not path or not path.exists():
        return []
    rules = json.loads(path.read_text(encoding="utf-8")).get("rules", [])
    for rule in rules:
        unknown = (set(rule.get("when", {})) - KNOWN_CONDITIONS) | (set(rule.get("then", {})) - KNOWN_ACTIONS)
        if unknown:
            raise ValueError(f"Rule {rule.get('name')!r}: unknown keys {sorted(unknown)}")
    return rules


def amounts(text):
    """All money amounts mentioned in the text, as floats ("$240", "£64.50", "120 GBP")."""
    found = []
    for match in AMOUNT_RE.finditer(text):
        value = (match.group(1) or match.group(2)).replace(",", "")
        found.append(float(value))
    return found


def matches(rule, item):
    text = f"{item['subject']}\n{item['body']}".lower()
    when = rule.get("when", {})
    if "intent_in" in when and item["intent"] not in when["intent_in"]:
        return False
    if "keywords_any" in when and not any(k.lower() in text for k in when["keywords_any"]):
        return False
    if "amount_over" in when and not any(a > when["amount_over"] for a in amounts(text)):
        return False
    if "sender_domain_in" in when:
        domain = item["sender_email"].rsplit("@", 1)[-1].lower()
        if domain not in [d.lower() for d in when["sender_domain_in"]]:
            return False
    if "priority_in" in when and item.get("priority") not in when["priority_in"]:
        return False
    return True


def apply_rules(item, rules):
    """Update item in place (priority, labels, escalate_to, notes) and record which rules fired."""
    item.setdefault("rules_applied", [])
    item.setdefault("notes", [])
    for rule in rules:
        if not matches(rule, item):
            continue
        then = rule.get("then", {})
        item["rules_applied"].append(rule["name"])
        if then.get("priority"):
            item["priority"] = then["priority"]
        for label in then.get("add_labels", []):
            if label not in item["labels"]:
                item["labels"].append(label)
        if then.get("escalate_to"):
            item["escalate_to"] = then["escalate_to"]
        item["notes"].append(then.get("note", ""))  # same index as rules_applied
    return item

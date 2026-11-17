"""Follow-up tracker: threads where we replied last and the customer has not answered for N days."""

from datetime import datetime

from .inbox import IncomingEmail


def _thread_key(mail, parent_of):
    """Walk In-Reply-To / References up to the first message of the thread."""
    key = mail.message_id
    seen = set()
    while key in parent_of and key not in seen:
        seen.add(key)
        key = parent_of[key]
    return key or mail.source


def group_threads(messages):
    parent_of = {}
    for mail in messages:
        parent = mail.in_reply_to or (mail.references.split()[-1] if mail.references else "")
        if mail.message_id and parent:
            parent_of[mail.message_id] = parent
    threads = {}
    for mail in messages:
        threads.setdefault(_thread_key(mail, parent_of), []).append(mail)
    for msgs in threads.values():
        msgs.sort(key=lambda m: m.date_iso)
    return threads


def find_followups(messages: list[IncomingEmail], our_addresses, now: datetime, days=3):
    """Return threads whose last message is ours, oldest first, with status 'overdue' or 'waiting'."""
    ours = {a.lower() for a in our_addresses}
    found = []
    for msgs in group_threads([m for m in messages if m.date_iso]).values():
        last = msgs[-1]
        if last.sender_email not in ours:
            continue  # the customer spoke last: nothing to chase
        waited = now - datetime.fromisoformat(last.date_iso)
        customer = next((m for m in msgs if m.sender_email not in ours), None)
        found.append({
            "subject": msgs[0].subject,
            "customer": f"{customer.sender_name} <{customer.sender_email}>" if customer else last.to_email,
            "last_reply": last.date,
            "days_waiting": round(waited.total_seconds() / 86400, 1),
            "status": "overdue" if waited.total_seconds() > days * 86400 else "waiting",
            "messages": len(msgs),
        })
    return sorted(found, key=lambda f: -f["days_waiting"])


def demo_now(messages):
    """For the sample data, 'now' is the newest message, so the demo gives the same result on any day."""
    stamps = [datetime.fromisoformat(m.date_iso) for m in messages if m.date_iso]
    return max(stamps) if stamps else None

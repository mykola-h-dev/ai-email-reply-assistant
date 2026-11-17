"""Build reply drafts as RFC 822 messages. These are saved or put in a Drafts folder - never sent."""

from email.message import EmailMessage


def build_draft_eml(to, subject, in_reply_to, draft_text, from_addr, status="needs-human-review"):
    msg = EmailMessage()
    msg["To"] = to
    msg["From"] = from_addr
    msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg["X-Draft-Status"] = status
    msg.set_content(draft_text)
    return bytes(msg)


def draft_for_item(item, draft_text, from_addr, status="needs-human-review"):
    return build_draft_eml(item["sender_email"], item["subject"], item.get("message_id", ""),
                           draft_text, from_addr, status)

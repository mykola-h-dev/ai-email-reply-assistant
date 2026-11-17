"""Read incoming emails from a folder of .eml files (demo) or an IMAP mailbox (read-only)."""

import email
import html
import imaplib
import re
from dataclasses import dataclass
from email import policy
from email.utils import parseaddr, parsedate_to_datetime


@dataclass
class IncomingEmail:
    message_id: str
    sender_name: str
    sender_email: str
    subject: str
    date: str
    body: str
    source: str  # file name or IMAP UID


def html_to_text(markup):
    """Very small HTML-to-text conversion, enough for typical customer emails."""
    markup = re.sub(r"(?is)<(script|style).*?</\1>", " ", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", markup)
    text = html.unescape(re.sub(r"<[^>]+>", "", markup))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def strip_quoted_reply(text):
    """Drop the quoted history below 'On ... wrote:' or '>' lines, so we classify only the new message."""
    lines = []
    for line in text.splitlines():
        if re.match(r"^On .+ wrote:$", line.strip()) or line.startswith(">"):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def parse_message(raw_bytes, source):
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)
    part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if part is not None:
        content = part.get_content()
        body = html_to_text(content) if part.get_content_type() == "text/html" else content
    name, address = parseaddr(msg.get("From", ""))
    try:
        date = parsedate_to_datetime(msg["Date"]).strftime("%Y-%m-%d %H:%M") if msg["Date"] else ""
    except (TypeError, ValueError):
        date = ""
    return IncomingEmail(
        message_id=msg.get("Message-ID", ""),
        sender_name=name or address.split("@")[0],
        sender_email=address.lower(),
        subject=str(msg.get("Subject", "")).strip(),
        date=date,
        body=strip_quoted_reply(body.strip()),
        source=source,
    )


def read_folder(folder):
    """Demo source: every .eml file in a folder, sorted by name."""
    return [parse_message(path.read_bytes(), path.name) for path in sorted(folder.glob("*.eml"))]


def read_imap(host, user, password, mailbox="INBOX", limit=20, port=993):
    """Real source: unread emails over IMAP SSL, opened READ-ONLY.

    The mailbox is selected with readonly=True and messages are fetched with
    BODY.PEEK[], so nothing is marked as read, moved or deleted.
    """
    with imaplib.IMAP4_SSL(host, port) as conn:
        conn.login(user, password)
        conn.select(mailbox, readonly=True)
        _, data = conn.uid("search", None, "UNSEEN")
        uids = data[0].split()[-limit:]
        emails = []
        for uid in uids:
            _, msg_data = conn.uid("fetch", uid, "(BODY.PEEK[])")
            raw = next((part[1] for part in msg_data if isinstance(part, tuple)), None)
            if raw:
                emails.append(parse_message(raw, f"IMAP UID {uid.decode()}"))
        conn.logout()
        return emails

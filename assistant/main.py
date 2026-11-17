"""Command-line entry point: read emails -> classify -> draft -> save for human review.

This tool NEVER sends email. It writes:
  drafts/<n>-<intent>.eml   one draft per email (open in any mail client, edit, send yourself)
  drafts/drafts.json        machine-readable results (for a Google Sheet, n8n, a helpdesk...)
  drafts/report.html        review page with every email, intent, confidence and draft

Examples:
  python -m assistant.main                      # demo: sample_inbox/ folder
  python -m assistant.main --source imap        # real mailbox, read-only (settings in .env)
"""

import argparse
import json
import logging
import os
import pathlib
import sys
from email.message import EmailMessage

from . import llm
from .classifier import classify
from .drafter import draft_reply, load_company
from .inbox import read_folder, read_imap
from .report import build_report

ROOT = pathlib.Path(__file__).resolve().parent.parent
log = logging.getLogger("email-assistant")


def load_dotenv(path=ROOT / ".env"):
    """Load KEY=VALUE lines from a local .env file; real environment variables win."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Classify customer emails and draft replies for human review.")
    p.add_argument("--source", choices=["folder", "imap"], default="folder")
    p.add_argument("--inbox", type=pathlib.Path, default=ROOT / "sample_inbox", help=".eml folder for --source folder")
    p.add_argument("--out", type=pathlib.Path, default=ROOT / "drafts")
    p.add_argument("--templates", type=pathlib.Path, default=ROOT / "templates")
    p.add_argument("--offline", action="store_true", help="ignore API keys and use rules + templates only")
    return p.parse_args(argv)


def fetch_emails(args):
    if args.source == "imap":
        missing = [k for k in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD") if not os.environ.get(k)]
        if missing:
            raise SystemExit(f"Missing settings for IMAP: {', '.join(missing)} (see .env.example)")
        return read_imap(os.environ["IMAP_HOST"], os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"],
                         mailbox=os.environ.get("IMAP_MAILBOX", "INBOX"),
                         limit=int(os.environ.get("IMAP_LIMIT", "20")))
    return read_folder(args.inbox)


def build_draft_eml(incoming, draft_text, company_email):
    """A draft as an .eml file, threaded to the original. Saved to disk only - never sent."""
    msg = EmailMessage()
    msg["To"] = incoming.sender_email
    msg["From"] = company_email
    msg["Subject"] = incoming.subject if incoming.subject.lower().startswith("re:") else f"Re: {incoming.subject}"
    if incoming.message_id:
        msg["In-Reply-To"] = incoming.message_id
        msg["References"] = incoming.message_id
    msg["X-Draft-Status"] = "needs-human-review"
    msg.set_content(draft_text)
    return bytes(msg)


def process(emails, templates_dir, use_llm):
    company = load_company(templates_dir)
    results = []
    for incoming in emails:
        intent = classify(incoming.subject, incoming.body, use_llm)
        draft, drafted_by = draft_reply(incoming, intent["intent"], templates_dir, company, use_llm)
        results.append({
            "source": incoming.source, "from": f"{incoming.sender_name} <{incoming.sender_email}>",
            "sender_email": incoming.sender_email, "subject": incoming.subject, "date": incoming.date,
            "body": incoming.body, "message_id": incoming.message_id,
            "intent": intent["intent"], "label": intent["label"], "confidence": intent["confidence"],
            "classified_by": intent["method"], "draft": draft, "drafted_by": drafted_by,
        })
        log.info("%-14s %-13s %.2f  %s", incoming.source, intent["intent"], intent["confidence"], incoming.subject)
    return results, company


def save_outputs(results, emails, company, out_dir, mode):
    out_dir.mkdir(parents=True, exist_ok=True)
    sender = company.get("reply_from", "hello@brambleandco.example")
    for i, (item, incoming) in enumerate(zip(results, emails), start=1):
        (out_dir / f"{i:02d}-{item['intent']}.eml").write_bytes(build_draft_eml(incoming, item["draft"], sender))
    (out_dir / "drafts.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (out_dir / "report.html").write_text(build_report(results, mode), encoding="utf-8")


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv()
    args = parse_args(argv)
    use_llm = llm.is_available() and not args.offline
    mode = f"AI ({llm.provider_name()})" if use_llm else "offline demo (keyword rules + templates)"
    log.info("Mode: %s", mode)

    emails = fetch_emails(args)
    if not emails:
        log.info("No emails to process.")
        return 0
    results, company = process(emails, args.templates, use_llm)
    if use_llm and all(r["drafted_by"] == "template" for r in results):
        mode += " - AI calls failed, offline fallback used"
        log.warning("AI calls failed (check the API key / network); drafts were made from templates.")
    save_outputs(results, emails, company, args.out, mode)
    log.info("Saved %d drafts for review in %s (open report.html). Nothing was sent.", len(results), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

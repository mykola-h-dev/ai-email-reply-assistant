"""Command-line entry point: read emails -> classify -> triage -> rules -> FAQ -> draft -> save.

This tool NEVER sends email. It writes:
  drafts/<n>-<intent>.eml   one draft per email (open in any mail client, edit, send yourself)
  drafts/drafts.json        machine-readable results (read by the review UI, a sheet, n8n...)
  drafts/followups.json     threads waiting for a customer reply
  drafts/report.html        static review page

Then review in the browser:  python -m assistant.review   (http://127.0.0.1:8030)

Examples:
  python -m assistant.main                      # demo: sample_inbox/ folder
  python -m assistant.main --source imap        # real mailbox, read-only (settings in .env)
"""

import argparse
import hashlib
import json
import logging
import os
import pathlib
import sys
from datetime import datetime, timezone

from . import llm
from .classifier import classify
from .drafter import draft_reply, load_company
from .eml import build_draft_eml
from .followups import demo_now, find_followups
from .inbox import read_folder, read_imap
from .knowledge import KnowledgeBase
from .report import build_report
from .rules import apply_rules, load_rules
from .triage import triage

ROOT = pathlib.Path(__file__).resolve().parent.parent
log = logging.getLogger("email-assistant")


def load_dotenv(path=ROOT / ".env"):
    """Load KEY=VALUE lines from the project's own .env file; real environment variables win."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Classify customer emails and draft replies for human review.")
    p.add_argument("--source", choices=["folder", "imap"], default="folder")
    p.add_argument("--inbox", type=pathlib.Path, default=ROOT / "sample_inbox", help=".eml folder for --source folder")
    p.add_argument("--history", type=pathlib.Path, default=ROOT / "sample_history",
                   help="folder of older .eml threads (incl. our sent replies) for the follow-up tracker")
    p.add_argument("--out", type=pathlib.Path, default=ROOT / "drafts")
    p.add_argument("--templates", type=pathlib.Path, default=ROOT / "templates")
    p.add_argument("--rules", type=pathlib.Path, default=ROOT / "rules.json")
    p.add_argument("--knowledge", type=pathlib.Path, default=ROOT / "knowledge" / "faq.json")
    p.add_argument("--followup-days", type=float, default=3, help="chase threads with no customer reply after N days")
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


def stable_id(incoming):
    return hashlib.sha1((incoming.message_id or incoming.source).encode()).hexdigest()[:10]


def process(emails, templates_dir, use_llm, rules=(), kb=None):
    company = load_company(templates_dir)
    results = []
    for incoming in emails:
        intent = classify(incoming.subject, incoming.body, use_llm)
        tri = triage(incoming.subject, incoming.body, intent["intent"], use_llm)
        faq_hits = kb.search(f"{incoming.subject}\n{incoming.body}") if kb else []
        draft, drafted_by = draft_reply(incoming, intent["intent"], templates_dir, company, use_llm, faq_hits)
        item = {
            "id": stable_id(incoming),
            "source": incoming.source, "from": f"{incoming.sender_name} <{incoming.sender_email}>",
            "sender_email": incoming.sender_email, "subject": incoming.subject, "date": incoming.date,
            "body": incoming.body, "message_id": incoming.message_id,
            "intent": intent["intent"], "label": intent["label"], "confidence": intent["confidence"],
            "classified_by": intent["method"],
            "summary": tri["summary"], "priority": tri["priority"], "labels": tri["labels"],
            "triaged_by": tri["triaged_by"], "escalate_to": "", "rules_applied": [], "notes": [],
            "faq": [e.as_dict(score) for score, e in faq_hits],
            "faq_in_draft": bool(faq_hits) and (drafted_by == "ai" or intent["intent"] == "other"),
            "draft": draft, "drafted_by": drafted_by,
        }
        apply_rules(item, rules)
        if item["escalate_to"]:
            item["draft"] = f"[CHECK: escalated to {item['escalate_to']} - get approval before sending]\n\n{item['draft']}"
        results.append(item)
        log.info("%-8s %-13s %-7s %.2f  %s", incoming.source, intent["intent"], item["priority"],
                 intent["confidence"], incoming.subject)
    return results, company


def build_followups(args, emails, company):
    history = read_folder(args.history) if args.source == "folder" and args.history.exists() else []
    everything = history + emails
    ours = {company.get("reply_from", "").split("<")[-1].strip("> ").lower()} - {""}
    now = demo_now(everything) if args.source == "folder" else datetime.now(timezone.utc)
    if now is None:
        return []
    return find_followups(everything, ours, now, args.followup_days)


def save_outputs(results, emails, company, out_dir, mode, followups=()):
    out_dir.mkdir(parents=True, exist_ok=True)
    sender = company.get("reply_from", "hello@brambleandco.example")
    for old in out_dir.glob("[0-9][0-9]-*.eml"):
        old.unlink()  # drafts from an earlier run with a different inbox
    for i, (item, incoming) in enumerate(zip(results, emails), start=1):
        raw = build_draft_eml(incoming.sender_email, incoming.subject, incoming.message_id, item["draft"], sender)
        (out_dir / f"{i:02d}-{item['intent']}.eml").write_bytes(raw)
    (out_dir / "drafts.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (out_dir / "followups.json").write_text(json.dumps(list(followups), indent=2), encoding="utf-8")
    (out_dir / "run.json").write_text(json.dumps({"mode": mode}), encoding="utf-8")
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
    rules = load_rules(args.rules)
    kb = KnowledgeBase.load(args.knowledge) if args.knowledge.exists() else None
    results, company = process(emails, args.templates, use_llm, rules, kb)
    if use_llm and all(r["drafted_by"] == "template" for r in results):
        mode += " - AI calls failed, offline fallback used"
        log.warning("AI calls failed (check the API key / network); drafts were made from templates.")
    followups = build_followups(args, emails, company)
    save_outputs(results, emails, company, args.out, mode, followups)
    overdue = sum(f["status"] == "overdue" for f in followups)
    log.info("Saved %d drafts for review in %s. Follow-ups overdue: %d. Nothing was sent.",
             len(results), args.out, overdue)
    log.info("Review them in the browser: python -m assistant.review")
    return 0


if __name__ == "__main__":
    sys.exit(main())

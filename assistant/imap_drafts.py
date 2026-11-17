"""Put approved drafts into the mailbox's Drafts folder with IMAP APPEND. NEVER sends anything.

Off by default. It only runs with the explicit --imap-append flag AND the IMAP_HOST,
IMAP_USER and IMAP_PASSWORD environment variables. Without the flag it is a dry run
that lists what would be appended.

    python -m assistant.imap_drafts               # dry run
    python -m assistant.imap_drafts --imap-append # append approved drafts to Drafts

Gmail's folder is "[Gmail]/Drafts" (set IMAP_DRAFTS_FOLDER). There is no SMTP code
in this project: a person opens the draft in their mail client and presses Send.
"""

import argparse
import imaplib
import logging
import os
import pathlib
import sys
import time

log = logging.getLogger("email-assistant")
REQUIRED_ENV = ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD")


class ImapConfigError(RuntimeError):
    pass


def imap_settings():
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise ImapConfigError(f"Missing settings for IMAP APPEND: {', '.join(missing)}")
    return {"host": os.environ["IMAP_HOST"], "user": os.environ["IMAP_USER"],
            "password": os.environ["IMAP_PASSWORD"], "port": int(os.environ.get("IMAP_PORT", "993")),
            "folder": os.environ.get("IMAP_DRAFTS_FOLDER", "Drafts")}


def append_drafts(raw_messages, settings, connect=imaplib.IMAP4_SSL):
    """APPEND each raw message to the Drafts folder with the \\Draft flag. Returns how many were stored."""
    conn = connect(settings["host"], settings["port"])
    stored = 0
    try:
        conn.login(settings["user"], settings["password"])
        for raw in raw_messages:
            typ, _ = conn.append(settings["folder"], r"(\Draft)", imaplib.Time2Internaldate(time.time()), raw)
            if typ != "OK":
                raise RuntimeError(f"IMAP APPEND failed with {typ}")
            stored += 1
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001 - logout errors must not hide the real result
            pass
    return stored


def main(argv=None):
    from .main import ROOT, load_dotenv
    from .store import ReviewStore
    from .drafter import load_company

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv()
    p = argparse.ArgumentParser(description="Append approved drafts to the IMAP Drafts folder (never sends).")
    p.add_argument("--imap-append", action="store_true", help="really append; without it this is a dry run")
    p.add_argument("--out", type=pathlib.Path, default=ROOT / "drafts")
    p.add_argument("--templates", type=pathlib.Path, default=ROOT / "templates")
    args = p.parse_args(argv)

    store = ReviewStore(args.out, load_company(args.templates).get("reply_from", ""))
    todo = [i for i in store.merged() if i["status"] == "approved" and not i["imap"].startswith("appended")]
    for item in todo:
        log.info("%s  %s  ->  %s", item["id"], item["subject"], item["sender_email"])
    if not args.imap_append:
        log.info("Dry run: %d approved draft(s) would be appended. Add --imap-append to do it.", len(todo))
        return 0
    try:
        settings = imap_settings()
    except ImapConfigError as exc:
        log.error("%s", exc)
        return 2
    count = append_drafts([store.approved_eml(i) for i in todo], settings)
    for item in todo:
        store.mark_imap(item["id"], f"appended to {settings['folder']}")
    log.info("Appended %d draft(s) to %s. Nothing was sent.", count, settings["folder"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

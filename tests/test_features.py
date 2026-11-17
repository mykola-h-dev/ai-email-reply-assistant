"""Offline tests for triage, rules, knowledge base, follow-ups, review store/UI and IMAP append."""

import json
import logging
import os
import pathlib
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from unittest import mock

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)

from assistant import imap_drafts, triage  # noqa: E402
from assistant.followups import demo_now, find_followups  # noqa: E402
from assistant.inbox import read_folder  # noqa: E402
from assistant.knowledge import KnowledgeBase  # noqa: E402
from assistant.main import main  # noqa: E402
from assistant.review import make_handler  # noqa: E402
from assistant.rules import amounts, apply_rules, load_rules  # noqa: E402
from assistant.store import ReviewStore  # noqa: E402

logging.disable(logging.CRITICAL)  # keep test output readable
ROOT = pathlib.Path(__file__).resolve().parent.parent
SHOP = "hello@brambleandco.example"


TEMP_DIRS = []


def tearDownModule():
    for path in TEMP_DIRS:
        shutil.rmtree(path, ignore_errors=True)


def run_offline():
    out = pathlib.Path(tempfile.mkdtemp())
    TEMP_DIRS.append(out)
    assert main(["--offline", "--out", str(out)]) == 0
    items = json.loads((out / "drafts.json").read_text())
    return out, {i["source"]: i for i in items}


class TriageTests(unittest.TestCase):
    def test_priority_rules(self):
        self.assertEqual(triage.priority_rules("Help", "This is unacceptable", "complaint"), "urgent")
        self.assertEqual(triage.priority_rules("Q", "No rush, whenever you can.", "other"), "low")
        self.assertEqual(triage.priority_rules("Order", "Where is my parcel?", "order_status"), "normal")

    def test_summary_skips_greeting_and_signature(self):
        body = "Hello Bramble & Co team,\n\nI run a small cafe and want 60 mugs.\n\nKind regards,\nHannah"
        self.assertEqual(triage.summarize("x", body), "I run a small cafe and want 60 mugs.")

    def test_labels(self):
        labels = triage.labels_rules("Broken vase", "It arrived smashed, I want a refund", "complaint")
        self.assertEqual(labels[0], "Complaint")
        self.assertIn("Damaged item", labels)
        self.assertIn("Payment", labels)

    def test_ai_triage_used_when_valid(self):
        reply = '{"summary": "Customer wants a refund.", "priority": "urgent", "labels": ["Refund", "VIP"]}'
        with mock.patch("assistant.llm.generate", return_value=reply):
            result = triage.triage("s", "b", "refund", use_llm=True)
        self.assertEqual((result["priority"], result["triaged_by"]), ("urgent", "ai"))
        self.assertEqual(result["labels"], ["Refund", "VIP"])

    def test_ai_triage_falls_back_on_error_or_bad_json(self):
        for side_effect in (RuntimeError("down"), None):
            kwargs = {"side_effect": side_effect} if side_effect else {"return_value": '{"priority": "whatever"}'}
            with mock.patch("assistant.llm.generate", **kwargs):
                result = triage.triage("Refund", "No rush, refund please", "refund", use_llm=True)
            self.assertEqual(result["triaged_by"], "rules")
            self.assertEqual(result["priority"], "low")


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.rules = load_rules(ROOT / "rules.json")

    def item(self, body, intent="refund", sender="a@example.com"):
        return {"subject": "s", "body": body, "intent": intent, "sender_email": sender,
                "priority": "normal", "labels": ["Refund"], "escalate_to": ""}

    def test_amount_parsing(self):
        self.assertEqual(amounts("total $240, plus £64.50 and 1,200 EUR"), [240.0, 64.5, 1200.0])

    def test_refund_over_100_escalates(self):
        item = apply_rules(self.item("The order total was $240."), self.rules)
        self.assertEqual(item["escalate_to"], "manager@brambleandco.example")
        self.assertIn("Escalated", item["labels"])

    def test_refund_under_100_does_not_escalate(self):
        item = apply_rules(self.item("The order total was $64."), self.rules)
        self.assertEqual(item["escalate_to"], "")

    def test_amount_rule_needs_refund_intent(self):
        item = apply_rules(self.item("Can I order $500 of mugs?", intent="other"), self.rules)
        self.assertEqual(item["rules_applied"], [])

    def test_chargeback_is_urgent_and_domain_label(self):
        item = apply_rules(self.item("I will open a chargeback", sender="x@example-cafe.example"), self.rules)
        self.assertEqual(item["priority"], "urgent")
        self.assertIn("Legal risk", item["labels"])
        self.assertIn("Trade account", item["labels"])

    def test_unknown_rule_key_is_rejected(self):
        folder = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        path = folder / "rules.json"
        path.write_text(json.dumps({"rules": [{"name": "bad", "when": {"colour": "red"}, "then": {}}]}))
        with self.assertRaises(ValueError):
            load_rules(path)


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeBase.load(ROOT / "knowledge" / "faq.json")

    def test_finds_relevant_entries(self):
        self.assertEqual(self.kb.search("Do you offer wholesale prices for 60 mugs?")[0][1].id, "FAQ-04")
        self.assertEqual(self.kb.search("my vase arrived smashed")[0][1].id, "FAQ-03")
        self.assertEqual(self.kb.search("can I pay with paypal")[0][1].id, "FAQ-10")

    def test_unrelated_text_has_no_grounding(self):
        self.assertEqual(self.kb.search("What is the weather on Mars?"), [])


class GroundedDraftTests(unittest.TestCase):
    def setUp(self):
        from assistant.drafter import load_company
        self.company = load_company(ROOT / "templates")
        self.kb = KnowledgeBase.load(ROOT / "knowledge" / "faq.json")
        self.mail = next(m for m in read_folder(ROOT / "sample_inbox") if m.source == "07.eml")

    def test_ai_prompt_contains_cited_faq(self):
        from assistant.drafter import draft_reply
        hits = self.kb.search(self.mail.body)
        with mock.patch("assistant.llm.generate", return_value="AI draft") as gen:
            text, method = draft_reply(self.mail, "other", ROOT / "templates", self.company, True, hits)
        self.assertEqual((text, method), ("AI draft", "ai"))
        self.assertIn("[FAQ-04]", gen.call_args[0][0])

    def test_ai_failure_falls_back_to_grounded_template(self):
        from assistant.drafter import draft_reply
        hits = self.kb.search(self.mail.body)
        with mock.patch("assistant.llm.generate", side_effect=RuntimeError("quota")):
            text, method = draft_reply(self.mail, "other", ROOT / "templates", self.company, True, hits)
        self.assertEqual(method, "template")
        self.assertIn("trade prices", text)


class FollowupTests(unittest.TestCase):
    def test_sample_history(self):
        msgs = read_folder(ROOT / "sample_history") + read_folder(ROOT / "sample_inbox")
        found = find_followups(msgs, {SHOP}, demo_now(msgs), days=3)
        by_subject = {f["subject"]: f for f in found}
        self.assertEqual(by_subject["Chipped bowl in order BC-10301"]["status"], "overdue")
        self.assertEqual(by_subject["Gift card not received"]["status"], "waiting")
        self.assertNotIn("Mug colours", by_subject)  # the customer replied last
        self.assertEqual(found[0]["subject"], "Chipped bowl in order BC-10301")  # longest wait first

    def test_threshold(self):
        msgs = read_folder(ROOT / "sample_history")
        later = datetime(2026, 11, 30, tzinfo=timezone.utc)
        self.assertTrue(all(f["status"] == "overdue" for f in find_followups(msgs, {SHOP}, later, days=3)))


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, cls.items = run_offline()

    def test_triage_and_rules_in_output(self):
        self.assertEqual(self.items["06.eml"]["priority"], "urgent")
        self.assertEqual(self.items["05.eml"]["priority"], "low")
        grace = self.items["09.eml"]
        self.assertEqual(grace["rules_applied"], ["Refund over $100 needs a manager"])
        self.assertTrue(grace["draft"].startswith("[CHECK: escalated to manager@brambleandco.example"))
        self.assertIn("Legal risk", self.items["10.eml"]["labels"])

    def test_faq_grounding(self):
        cafe = self.items["07.eml"]
        self.assertEqual(cafe["faq"][0]["id"], "FAQ-04")
        self.assertTrue(cafe["faq_in_draft"])
        self.assertIn("24 or more units", cafe["draft"])

    def test_followups_written(self):
        followups = json.loads((self.out / "followups.json").read_text())
        self.assertEqual([f["status"] for f in followups], ["overdue", "waiting"])

    def test_ids_are_stable(self):
        _, again = run_offline()
        self.assertEqual({k: v["id"] for k, v in again.items()}, {k: v["id"] for k, v in self.items.items()})


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.out, items = run_offline()
        self.store = ReviewStore(self.out, f"Bramble & Co <{SHOP}>")
        self.first = items["01.eml"]["id"]
        self.second = items["02.eml"]["id"]

    def test_edit_approve_discard_and_export(self):
        self.store.save_edit(self.first, "Hi Emma,\r\nEdited.\r\n")
        approved = self.store.approve(self.first)
        self.assertEqual((approved["status"], approved["draft"], approved["edited"]), ("approved", "Hi Emma,\nEdited.", True))
        self.store.discard(self.second)
        eml = (self.out / "approved" / f"{self.first}.eml").read_text()
        self.assertIn("X-Draft-Status: approved-by-reviewer", eml)
        self.assertIn("Edited.", eml)
        export = json.loads((self.out / "approved" / "approved.json").read_text())
        self.assertEqual([e["id"] for e in export], [self.first])
        # state survives a new store object (e.g. a server restart)
        self.assertEqual(ReviewStore(self.out, SHOP).get(self.second)["status"], "discarded")

    def test_reopen_removes_export(self):
        self.store.approve(self.first)
        self.store.reopen(self.first)
        self.assertEqual(list((self.out / "approved").glob("*.eml")), [])

    def test_errors(self):
        with self.assertRaises(KeyError):
            self.store.approve("0000000000")
        with self.assertRaises(ValueError):
            self.store.save_edit(self.first, "   ")


class FakeImap:
    """Stands in for imaplib.IMAP4_SSL. Records calls; has no way to send mail."""
    instances = []

    def __init__(self, host, port):
        self.host, self.port, self.appended, self.logged_in, self.closed = host, port, [], None, False
        FakeImap.instances.append(self)

    def login(self, user, password):
        self.logged_in = user
        return "OK", [b""]

    def append(self, folder, flags, date, raw):
        self.appended.append((folder, flags, raw))
        return "OK", [b"APPEND completed"]

    def logout(self):
        self.closed = True


IMAP_ENV = {"IMAP_HOST": "imap.example.test", "IMAP_USER": "demo@example.test", "IMAP_PASSWORD": "not-a-real-password"}


class ImapAppendTests(unittest.TestCase):
    def setUp(self):
        FakeImap.instances = []

    def test_append_uses_draft_flag_and_folder(self):
        with mock.patch.dict(os.environ, {**IMAP_ENV, "IMAP_DRAFTS_FOLDER": "[Gmail]/Drafts"}):
            settings = imap_drafts.imap_settings()
        stored = imap_drafts.append_drafts([b"Subject: a\r\n\r\nx", b"Subject: b\r\n\r\ny"], settings, connect=FakeImap)
        conn = FakeImap.instances[0]
        self.assertEqual(stored, 2)
        self.assertEqual(conn.appended[0][:2], ("[Gmail]/Drafts", r"(\Draft)"))
        self.assertTrue(conn.closed)
        self.assertFalse(hasattr(conn, "sendmail"))

    def test_missing_settings(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(imap_drafts.ImapConfigError):
                imap_drafts.imap_settings()

    def test_cli_is_dry_run_without_flag(self):
        out, items = run_offline()
        ReviewStore(out, SHOP).approve(items["01.eml"]["id"])
        with mock.patch.object(imap_drafts, "append_drafts") as append, mock.patch.dict(os.environ, IMAP_ENV):
            self.assertEqual(imap_drafts.main(["--out", str(out)]), 0)
        append.assert_not_called()

    def test_cli_with_flag_appends_approved_once(self):
        out, items = run_offline()
        ReviewStore(out, SHOP).approve(items["01.eml"]["id"])
        real = imap_drafts.append_drafts
        with mock.patch.object(imap_drafts, "append_drafts", side_effect=lambda raws, s: real(raws, s, connect=FakeImap)), \
                mock.patch.dict(os.environ, IMAP_ENV):
            self.assertEqual(imap_drafts.main(["--out", str(out), "--imap-append"]), 0)
            self.assertEqual(imap_drafts.main(["--out", str(out), "--imap-append"]), 0)
        self.assertEqual(sum(len(c.appended) for c in FakeImap.instances), 1)  # second run: already appended

    def test_cli_flag_without_settings_fails(self):
        out, _ = run_offline()
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(imap_drafts.main(["--out", str(out), "--imap-append"]), 2)


class ReviewServerTests(unittest.TestCase):
    def start(self, imap_append=False):
        self.out, self.items = run_offline()
        store = ReviewStore(self.out, SHOP)
        handler = make_handler(store, self.out, imap_append, imap_connect=FakeImap)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(shutil.rmtree, self.out, True)

    def call(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if path.startswith("/api") else raw.decode())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_page_list_and_actions(self):
        self.start()
        status, page = self.call("/")
        self.assertEqual(status, 200)
        self.assertIn("review queue", page)
        status, data = self.call("/api/drafts")
        self.assertEqual((len(data["items"]), data["imap_append"]), (10, False))
        first, second = self.items["01.eml"]["id"], self.items["02.eml"]["id"]
        self.assertEqual(self.call(f"/api/drafts/{first}/approve", {"draft": "Edited reply"})[1]["status"], "approved")
        self.assertEqual(self.call(f"/api/drafts/{second}/discard", {})[1]["status"], "discarded")
        self.assertEqual(self.call("/api/approved")[1][0]["draft"], "Edited reply")
        self.assertEqual(self.call("/api/followups")[1][0]["status"], "overdue")
        self.assertEqual(self.call(f"/api/drafts/{second}/save", {"draft": ""})[0], 400)
        self.assertEqual(self.call("/api/drafts/0000000000/approve", {})[0], 404)
        self.assertEqual(self.call("/api/nothing")[0], 404)

    def test_approve_appends_to_imap_only_when_enabled(self):
        FakeImap.instances = []
        self.start(imap_append=True)
        first = self.items["01.eml"]["id"]
        with mock.patch.dict(os.environ, IMAP_ENV):
            item = self.call(f"/api/drafts/{first}/approve", {})[1]
        self.assertEqual(item["imap"], "appended to Drafts")
        self.assertEqual(len(FakeImap.instances[0].appended), 1)

    def test_imap_failure_keeps_approval(self):
        self.start(imap_append=True)
        first = self.items["01.eml"]["id"]
        with mock.patch.dict(os.environ, {}, clear=True):
            item = self.call(f"/api/drafts/{first}/approve", {})[1]
        self.assertEqual(item["status"], "approved")
        self.assertTrue(item["imap"].startswith("IMAP append failed"))


if __name__ == "__main__":
    unittest.main()

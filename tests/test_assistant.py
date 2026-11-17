"""Offline tests: python -m unittest discover tests"""

import os
import pathlib
import tempfile
import unittest

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)

from assistant.classifier import classify  # noqa: E402
from assistant.inbox import html_to_text, read_folder, strip_quoted_reply  # noqa: E402
from assistant.main import main  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXPECTED = {"01.eml": "order_status", "02.eml": "order_status", "03.eml": "refund", "04.eml": "refund",
            "05.eml": "booking", "06.eml": "complaint", "07.eml": "other", "08.eml": "refund"}


class AssistantTests(unittest.TestCase):
    def test_sample_inbox_intents(self):
        for mail in read_folder(ROOT / "sample_inbox"):
            result = classify(mail.subject, mail.body, use_llm=False)
            self.assertEqual(result["intent"], EXPECTED[mail.source], mail.subject)
            self.assertTrue(0 < result["confidence"] <= 0.95)

    def test_html_only_email_is_read(self):
        mail = next(m for m in read_folder(ROOT / "sample_inbox") if m.source == "08.eml")
        self.assertIn("glass carafe is cracked", mail.body)
        self.assertNotIn("<p>", mail.body)

    def test_helpers(self):
        self.assertEqual(html_to_text("<p>Hi &amp; bye</p><br>x"), "Hi & bye\n\nx")
        self.assertEqual(strip_quoted_reply("Thanks!\nOn Mon, Bob wrote:\n> old"), "Thanks!")

    def test_end_to_end_writes_drafts_and_report(self):
        out = pathlib.Path(tempfile.mkdtemp())
        self.assertEqual(main(["--offline", "--out", str(out)]), 0)
        drafts = sorted(p.name for p in out.glob("*.eml"))
        self.assertEqual(len(drafts), 8)
        self.assertIn("01-order_status.eml", drafts)
        first = (out / "01-order_status.eml").read_text()
        self.assertIn("X-Draft-Status: needs-human-review", first)
        self.assertIn("In-Reply-To: <sample-001@example.com>", first)
        report = (out / "report.html").read_text()
        self.assertIn("Nothing has been sent", report)
        self.assertIn("Low confidence", report)

    def test_missing_order_number_reads_naturally(self):
        out = pathlib.Path(tempfile.mkdtemp())
        main(["--offline", "--out", str(out)])
        booking = (out / "05-booking.eml").read_text()
        self.assertNotIn("$", booking)  # every template placeholder was filled


if __name__ == "__main__":
    unittest.main()

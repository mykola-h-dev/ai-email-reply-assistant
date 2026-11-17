"""Create the fictional sample inbox (sample_inbox/*.eml).

All people, companies, addresses and order numbers are made up.
Run: python scripts/make_sample_inbox.py
"""

import pathlib
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone, timedelta

OUT = pathlib.Path(__file__).resolve().parent.parent / "sample_inbox"
SHOP = "hello@brambleandco.example"
START = datetime(2026, 11, 16, 8, 5, tzinfo=timezone.utc)

EMAILS = [
    ("Emma Carter <emma.carter@example.com>", "Where is my order?",
     "Hi,\n\nI ordered a linen throw and two mugs last Tuesday (order #BC-10482) and it still "
     "shows as processing. Could you tell me when it will ship?\n\nThanks,\nEmma"),
    ("Liam Walsh <liam.walsh@example.net>", "Tracking number for order BC-10517",
     "Hello, can you send me the tracking number for order BC-10517? The confirmation email "
     "didn't include one. Cheers, Liam"),
    ("Sofia Nguyen <sofia.n@example.org>", "Refund request - wrong size",
     "Hi there,\n\nThe table runner I received (order BC-10391) is too short for our table. "
     "I'd like to return it and get a refund please. It's unused and still in the packaging.\n\nBest,\nSofia Nguyen"),
    ("Daniel Brooks <dbrooks@example.com>", "Money back for cancelled item",
     "I cancelled the oak shelf from my order two weeks ago but I have not been refunded yet. "
     "Please can you check and reimburse me. Order number BC-10233.\n\nDaniel"),
    ("Priya Shah <priya.shah@example.com>", "Booking the pottery workshop",
     "Hi! I'd love to book two places on your Saturday pottery workshop, ideally 6 December. "
     "Are there still spaces available, and how do I pay?\n\nPriya"),
    ("Mark O'Neill <mark.oneill@example.net>", "Very disappointed - broken vase",
     "This is the second time an order from you has arrived damaged. The ceramic vase in order "
     "BC-10455 was smashed and the box was barely padded. Honestly this is unacceptable and I "
     "expect better.\n\nMark O'Neill"),
    ("Hannah Lee <hannah@example-cafe.example>", "Wholesale enquiry for our cafe",
     "Hello Bramble & Co team,\n\nI run a small cafe and would like to know if you offer "
     "wholesale prices for your stoneware mugs (around 60 units).\n\nKind regards,\nHannah Lee"),
]

HTML_EMAIL = ("Oliver Grant <oliver.grant@example.com>", "Order BC-10560 arrived damaged - refund?",
              "<html><body><p>Hi,</p><p>My order <b>BC-10560</b> arrived today but the glass "
              "carafe is cracked. I'd prefer a <i>refund</i> rather than a replacement.</p>"
              "<p>Photos attached in my next email.</p><p>Oliver</p></body></html>")


def build(index, sender, subject, body, html=False):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = f"Bramble & Co <{SHOP}>"
    msg["Subject"] = subject
    msg["Date"] = format_datetime(START + timedelta(minutes=37 * index))
    msg["Message-ID"] = f"<sample-{index:03d}@example.com>"
    msg.set_content(body, subtype="html" if html else "plain")  # one HTML-only email tests HTML parsing
    return msg


def main():
    OUT.mkdir(exist_ok=True)
    items = [(s, sub, b, False) for s, sub, b in EMAILS] + [(*HTML_EMAIL, True)]
    for i, (sender, subject, body, html) in enumerate(items, start=1):
        path = OUT / f"{i:02d}.eml"
        path.write_bytes(bytes(build(i, sender, subject, body, html)))
    print(f"Wrote {len(items)} emails to {OUT}")


if __name__ == "__main__":
    main()

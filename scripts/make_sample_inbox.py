"""Create the fictional sample inbox (sample_inbox/*.eml).

All people, companies, addresses and order numbers are made up.
Run: python scripts/make_sample_inbox.py
"""

import pathlib
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "sample_inbox"
HISTORY = ROOT / "sample_history"  # older threads, used by the follow-up tracker
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
     "Are there still spaces available, and how do I pay? No rush, whenever you get a chance.\n\nPriya"),
    ("Mark O'Neill <mark.oneill@example.net>", "Very disappointed - broken vase",
     "This is the second time an order from you has arrived damaged. The ceramic vase in order "
     "BC-10455 was smashed and the box was barely padded. Honestly this is unacceptable and I "
     "expect better.\n\nMark O'Neill"),
    ("Hannah Lee <hannah@example-cafe.example>", "Wholesale enquiry for our cafe",
     "Hello Bramble & Co team,\n\nI run a small cafe and would like to know if you offer "
     "wholesale prices for your stoneware mugs (around 60 units).\n\nKind regards,\nHannah Lee"),
]

EXTRA_EMAILS = [
    ("Grace Fitzgerald <grace.fitz@example.co.uk>", "Refund for order BC-10602 - dining chairs",
     "Hello,\n\nI returned the two oak dining chairs from order BC-10602 last week (tracking shows you "
     "received them on Friday). The order total was $240. Please can you confirm when the refund will "
     "be processed?\n\nThank you,\nGrace"),
    ("Tom Reilly <tom.reilly@example.com>", "Still no refund - I will open a chargeback",
     "I sent the faulty lamp back three weeks ago (order BC-10288) and I have still not had my refund of $64. "
     "Nobody has answered my last two emails. If I don't hear back by Friday I will open a chargeback "
     "with my bank.\n\nTom Reilly"),
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


# Older conversations: (thread, sender, to, subject, body, date, in_reply_to)
HISTORY_MESSAGES = [
    ("chloe-1", "Chloe Martin <chloe.m@example.com>", SHOP, "Chipped bowl in order BC-10301",
     "Hi, one of the bowls in my order arrived chipped. What should I do?\nChloe",
     datetime(2026, 11, 9, 9, 12, tzinfo=timezone.utc), None),
    ("chloe-2", f"Bramble & Co <{SHOP}>", "chloe.m@example.com", "Re: Chipped bowl in order BC-10301",
     "Hi Chloe,\n\nSorry about that! Could you send us a photo of the chip? We'll then send a replacement "
     "at no cost.\n\nBest wishes,\nThe Bramble & Co team",
     datetime(2026, 11, 10, 11, 40, tzinfo=timezone.utc), "chloe-1"),
    ("ben-1", "Ben Hughes <ben.hughes@example.net>", SHOP, "Gift card not received",
     "Hello, I bought a gift card for my sister but she hasn't received it. Ben",
     datetime(2026, 11, 14, 16, 3, tzinfo=timezone.utc), None),
    ("ben-2", f"Bramble & Co <{SHOP}>", "ben.hughes@example.net", "Re: Gift card not received",
     "Hi Ben,\n\nCould you reply with the order number and your sister's email address so we can "
     "re-send it?\n\nBest wishes,\nThe Bramble & Co team",
     datetime(2026, 11, 15, 10, 25, tzinfo=timezone.utc), "ben-1"),
    ("aisha-1", "Aisha Khan <aisha.khan@example.org>", SHOP, "Mug colours",
     "Hi, do the speckled mugs come in green?\nAisha",
     datetime(2026, 11, 7, 13, 0, tzinfo=timezone.utc), None),
    ("aisha-2", f"Bramble & Co <{SHOP}>", "aisha.khan@example.org", "Re: Mug colours",
     "Hi Aisha,\n\nThey come in sage green and oat. Would you like us to reserve some?\n\n"
     "Best wishes,\nThe Bramble & Co team",
     datetime(2026, 11, 8, 9, 30, tzinfo=timezone.utc), "aisha-1"),
    ("aisha-3", "Aisha Khan <aisha.khan@example.org>", SHOP, "Re: Mug colours",
     "Lovely, I've just ordered two in sage. Thanks!\nAisha",
     datetime(2026, 11, 8, 18, 45, tzinfo=timezone.utc), "aisha-2"),
]


def build_history():
    HISTORY.mkdir(exist_ok=True)
    ids = {}
    for i, (key, sender, to, subject, body, date, parent) in enumerate(HISTORY_MESSAGES, start=1):
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = format_datetime(date)
        ids[key] = f"<history-{key}@example.com>"
        msg["Message-ID"] = ids[key]
        if parent:
            msg["In-Reply-To"] = ids[parent]
            msg["References"] = ids[parent]
        msg.set_content(body)
        (HISTORY / f"h{i:02d}-{key}.eml").write_bytes(bytes(msg))
    print(f"Wrote {len(HISTORY_MESSAGES)} history emails to {HISTORY}")


def main():
    OUT.mkdir(exist_ok=True)
    items = ([(s, sub, b, False) for s, sub, b in EMAILS] + [(*HTML_EMAIL, True)]
             + [(s, sub, b, False) for s, sub, b in EXTRA_EMAILS])
    for i, (sender, subject, body, html) in enumerate(items, start=1):
        path = OUT / f"{i:02d}.eml"
        path.write_bytes(bytes(build(i, sender, subject, body, html)))
    print(f"Wrote {len(items)} emails to {OUT}")
    build_history()


if __name__ == "__main__":
    main()

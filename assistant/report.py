"""Build a self-contained HTML review page listing every email, its intent and the draft."""

import html
import re
from datetime import datetime

INTENT_COLORS = {"order_status": "#2563eb", "refund": "#9333ea", "booking": "#059669",
                 "complaint": "#dc2626", "other": "#6b7280"}
PRIORITY_COLORS = {"urgent": "#b91c1c", "normal": "#475569", "low": "#94a3b8"}
PRIORITY_ORDER = {"urgent": 0, "normal": 1, "low": 2}
REVIEW_THRESHOLD = 0.75  # below this the card is flagged for a closer look

STYLE = """
:root { --bg:#f6f7f9; --card:#fff; --text:#1f2937; --muted:#6b7280; --line:#e5e7eb; }
* { box-sizing:border-box; }
body { margin:0; font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--text); }
header { padding:24px 5vw 8px; }
h1 { margin:0 0 4px; font-size:1.5rem; }
.sub { color:var(--muted); font-size:.92rem; }
.summary { display:flex; flex-wrap:wrap; gap:8px; padding:12px 5vw 4px; }
.pill { font-size:.8rem; padding:4px 10px; border-radius:999px; color:#fff; font-weight:600; }
main { padding:12px 5vw 40px; display:grid; gap:16px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:14px; overflow:hidden; }
.card-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; padding:14px 18px; border-bottom:1px solid var(--line); }
.card-head h2 { font-size:1rem; margin:0 0 3px; }
.meta { color:var(--muted); font-size:.82rem; }
.tags { display:flex; gap:6px; align-items:center; flex-shrink:0; }
.conf { font-size:.8rem; color:var(--muted); }
.flag { font-size:.75rem; background:#fef3c7; color:#92400e; padding:3px 8px; border-radius:999px; font-weight:600; }
.cols { display:grid; grid-template-columns:1fr 1fr; }
.cols > div { padding:14px 18px; }
.cols > div + div { border-left:1px solid var(--line); background:#fbfcfe; }
.label { text-transform:uppercase; letter-spacing:.06em; font-size:.7rem; color:var(--muted); font-weight:700; margin-bottom:6px; }
pre { white-space:pre-wrap; font-family:inherit; font-size:.88rem; line-height:1.5; margin:0; }
mark { background:#fef3c7; padding:0 2px; border-radius:3px; }
.extra { padding:10px 18px; border-bottom:1px solid var(--line); font-size:.86rem; display:grid; gap:4px; }
.lbl { font-size:.75rem; background:#eef2ff; color:#3730a3; padding:2px 8px; border-radius:999px; margin-right:4px; }
.note { color:#92400e; }
@media (max-width:760px) { .cols { grid-template-columns:1fr; } .cols > div + div { border-left:0; border-top:1px solid var(--line); } }
"""


def _esc(text):
    return html.escape(text or "")


def _highlight_checks(text):
    """Highlight [CHECK: ...] notes so the reviewer cannot miss them."""
    return re.sub(r"\[CHECK:[^\]]*\]", lambda m: f"<mark>{m.group()}</mark>", _esc(text))


def _card(item):
    color = INTENT_COLORS.get(item["intent"], "#6b7280")
    flag = '<span class="flag">Low confidence - review intent</span>' if item["confidence"] < REVIEW_THRESHOLD else ""
    return f"""
<article class="card">
  <div class="card-head">
    <div>
      <h2>{_esc(item['subject'])}</h2>
      <div class="meta">{_esc(item['from'])} &middot; {_esc(item['date'])} &middot; {_esc(item['source'])}</div>
    </div>
    <div class="tags">{flag}
      <span class="pill" style="background:{PRIORITY_COLORS.get(item.get('priority', 'normal'), '#475569')}">{_esc(item.get('priority', 'normal'))}</span>
      <span class="pill" style="background:{color}">{_esc(item['label'])}</span>
      <span class="conf">{item['confidence']:.0%} ({_esc(item['classified_by'])})</span>
    </div>
  </div>
  <div class="extra">
    <div><b>Summary:</b> {_esc(item.get('summary', ''))}</div>
    <div>{''.join(f'<span class="lbl">{_esc(l)}</span>' for l in item.get('labels', []))}</div>
    {''.join(f'<div class="note">Rule: {_esc(r)}{(" - " + _esc(n)) if n else ""}</div>' for r, n in zip(item.get('rules_applied', []), item.get('notes', [])))}
    {('<div>FAQ: ' + _esc(', '.join(f['id'] + ' ' + f['question'] for f in item.get('faq', []))) + '</div>') if item.get('faq') else ''}
  </div>
  <div class="cols">
    <div><div class="label">Customer email</div><pre>{_esc(item['body'])}</pre></div>
    <div><div class="label">Draft reply ({_esc(item['drafted_by'])}) - not sent</div><pre>{_highlight_checks(item['draft'])}</pre></div>
  </div>
</article>"""


def build_report(items, mode):
    counts = {}
    for item in items:
        counts[item["label"], item["intent"]] = counts.get((item["label"], item["intent"]), 0) + 1
    pills = "".join(f'<span class="pill" style="background:{INTENT_COLORS[intent]}">{_esc(label)}: {n}</span>'
                    for (label, intent), n in sorted(counts.items()))
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    # urgent first, then least confident, so the reviewer starts with the emails most likely to need a manual decision
    cards = "".join(_card(item) for item in sorted(items, key=lambda i: (PRIORITY_ORDER.get(i.get("priority"), 1), i["confidence"])))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Email drafts for review</title><style>{STYLE}</style></head>
<body>
<header>
  <h1>Email drafts for review</h1>
  <div class="sub">{len(items)} emails &middot; mode: {_esc(mode)} &middot; generated {generated} &middot;
  Nothing has been sent. Review each draft, fill in the highlighted notes, then send from your mail client.</div>
</header>
<div class="summary">{pills}</div>
<main>{cards}</main>
</body></html>"""

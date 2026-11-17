"""Review state for the web UI: pending / approved / discarded, plus edited draft text.

State lives in <out>/review_state.json, keyed by a stable id derived from the
email's Message-ID, so re-running the assistant keeps earlier decisions.
Approved drafts are exported to <out>/approved/<id>.eml and approved.json.
"""

import json
import threading
from datetime import datetime, timezone

from .eml import draft_for_item

STATUSES = ("pending", "approved", "discarded")


class ReviewStore:
    def __init__(self, out_dir, from_addr):
        self.out_dir = out_dir
        self.from_addr = from_addr
        self.path = out_dir / "review_state.json"
        self.approved_dir = out_dir / "approved"
        self._lock = threading.Lock()

    # --- data -------------------------------------------------------------
    def items(self):
        path = self.out_dir / "drafts.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def state(self):
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def _save_state(self, state):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def merged(self):
        """Every item with its review status and current (possibly edited) draft."""
        state = self.state()
        result = []
        for item in self.items():
            entry = state.get(item["id"], {})
            result.append({**item, "status": entry.get("status", "pending"),
                           "draft": entry.get("draft", item["draft"]), "edited": "draft" in entry,
                           "reviewed_at": entry.get("updated_at", ""), "imap": entry.get("imap", "")})
        return result

    def get(self, item_id):
        return next((i for i in self.merged() if i["id"] == item_id), None)

    # --- actions ----------------------------------------------------------
    def _update(self, item_id, **changes):
        with self._lock:
            if not any(i["id"] == item_id for i in self.items()):
                raise KeyError(item_id)
            state = self.state()
            entry = state.setdefault(item_id, {})
            entry.update(changes)
            entry["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            self._save_state(state)
            self._export_approved()
        return self.get(item_id)

    def save_edit(self, item_id, draft):
        return self._update(item_id, draft=_clean(draft))

    def approve(self, item_id, draft=None):
        changes = {"status": "approved"}
        if draft is not None:
            changes["draft"] = _clean(draft)
        return self._update(item_id, **changes)

    def discard(self, item_id):
        return self._update(item_id, status="discarded")

    def reopen(self, item_id):
        return self._update(item_id, status="pending")

    def mark_imap(self, item_id, result):
        return self._update(item_id, imap=result)

    # --- export -----------------------------------------------------------
    def approved_eml(self, item):
        return draft_for_item(item, item["draft"], self.from_addr, status="approved-by-reviewer")

    def _export_approved(self):
        """Rewrite approved/ so it always mirrors the current approvals."""
        self.approved_dir.mkdir(parents=True, exist_ok=True)
        for old in self.approved_dir.glob("*.eml"):
            old.unlink()
        approved = [i for i in self.merged() if i["status"] == "approved"]
        for item in approved:
            (self.approved_dir / f"{item['id']}.eml").write_bytes(self.approved_eml(item))
        export = [{k: item[k] for k in ("id", "sender_email", "subject", "priority", "labels",
                                         "escalate_to", "draft", "edited", "reviewed_at") if k in item}
                  for item in approved]
        (self.approved_dir / "approved.json").write_text(json.dumps(export, indent=2), encoding="utf-8")


def _clean(text):
    text = str(text).replace("\r\n", "\n").strip()
    if not text:
        raise ValueError("Draft text cannot be empty")
    return text[:20000]

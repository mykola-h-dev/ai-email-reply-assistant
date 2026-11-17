"""Web review UI for the drafts (Python standard library HTTP server).

    python -m assistant.review                 # http://127.0.0.1:8030
    python -m assistant.review --imap-append   # also APPEND approved drafts to the IMAP Drafts folder

Routes:
  GET  /                          review page
  GET  /api/drafts                drafts with triage, rules, FAQ citations and review status
  GET  /api/followups             threads waiting for a customer reply
  GET  /api/approved              export of approved drafts (JSON)
  POST /api/drafts/<id>/approve   {"draft": optional edited text}
  POST /api/drafts/<id>/save      {"draft": "..."}
  POST /api/drafts/<id>/discard
  POST /api/drafts/<id>/reopen
Nothing is ever sent: approval exports a draft file (and optionally an IMAP draft).
"""

import argparse
import json
import logging
import pathlib
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import imap_drafts
from .drafter import load_company
from .store import ReviewStore

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = pathlib.Path(__file__).resolve().parent / "web" / "review.html"
ACTION_RE = re.compile(r"^/api/drafts/([0-9a-f]{6,40})/(approve|save|discard|reopen)$")
MAX_BODY = 64_000
log = logging.getLogger("email-assistant")


def make_handler(store, out_dir, imap_append=False, imap_connect=None):
    class ReviewHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path in ("/", "/index.html"):
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if path == "/api/drafts":
                run = out_dir / "run.json"
                mode = json.loads(run.read_text())["mode"] if run.exists() else "unknown"
                return self._json({"mode": mode, "imap_append": imap_append, "items": store.merged()})
            if path == "/api/followups":
                f = out_dir / "followups.json"
                return self._json(json.loads(f.read_text()) if f.exists() else [])
            if path == "/api/approved":
                f = store.approved_dir / "approved.json"
                return self._json(json.loads(f.read_text()) if f.exists() else [])
            return self._json({"error": "Not found"}, 404)

        def do_POST(self):
            match = ACTION_RE.match(urlsplit(self.path).path)
            if not match:
                return self._json({"error": "Not found"}, 404)
            item_id, action = match.groups()
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length > MAX_BODY:
                    return self._json({"error": "Request too large"}, 413)
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("JSON object expected")
            except ValueError:
                return self._json({"error": "Invalid JSON"}, 400)
            try:
                if action == "save":
                    item = store.save_edit(item_id, payload.get("draft", ""))
                elif action == "approve":
                    item = store.approve(item_id, payload.get("draft"))
                    if imap_append:
                        item = self._append_to_imap(item)
                elif action == "discard":
                    item = store.discard(item_id)
                else:
                    item = store.reopen(item_id)
            except KeyError:
                return self._json({"error": "Unknown draft"}, 404)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            log.info("%s %s", action, item_id)
            return self._json(item)

        def _append_to_imap(self, item):
            try:
                settings = imap_drafts.imap_settings()
                kwargs = {"connect": imap_connect} if imap_connect else {}
                imap_drafts.append_drafts([store.approved_eml(item)], settings, **kwargs)
                result = f"appended to {settings['folder']}"
            except Exception as exc:  # noqa: BLE001 - approval is kept; the reviewer sees the error
                result = f"IMAP append failed: {type(exc).__name__}: {exc}"[:200]
            return store.mark_imap(item["id"], result)

        def _json(self, data, status=200):
            self._send(status, json.dumps(data).encode("utf-8"), "application/json")

        def _send(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            log.debug(fmt, *args)

    return ReviewHandler


def main(argv=None):
    from .main import load_dotenv

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv()
    p = argparse.ArgumentParser(description="Review, edit and approve reply drafts in the browser (never sends).")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8030)
    p.add_argument("--out", type=pathlib.Path, default=ROOT / "drafts")
    p.add_argument("--templates", type=pathlib.Path, default=ROOT / "templates")
    p.add_argument("--imap-append", action="store_true",
                   help="on approval, APPEND the draft to the IMAP Drafts folder (needs IMAP_* env)")
    args = p.parse_args(argv)
    if not (args.out / "drafts.json").exists():
        raise SystemExit("No drafts yet - run: python -m assistant.main")
    store = ReviewStore(args.out, load_company(args.templates).get("reply_from", ""))
    if args.imap_append:
        try:
            imap_drafts.imap_settings()  # fail fast if IMAP_* settings are missing
        except imap_drafts.ImapConfigError as exc:
            raise SystemExit(str(exc)) from exc
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store, args.out, args.imap_append))
    log.info("Review UI: http://%s:%d  (IMAP append: %s; nothing is ever sent)", args.host, args.port,
             "on" if args.imap_append else "off")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

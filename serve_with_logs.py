#!/usr/bin/env python3
"""
serve_with_logs.py — serve the StyleMate page and collect its Ollama audit logs.

Why this exists
---------------
A browser page cannot write a file to a folder on its own. It can only hand the
viewer a download, which lands wherever the browser is configured to put it.
So to get one audit file per request inside a logs/ subfolder, the page POSTs
each record here and this script writes it.

It also serves the folder over http://localhost, which is worth having anyway:
a page on http://localhost is a secure context, so the camera in the colour
studio works, and there is no file:// weirdness around fetch.

Run it from the folder holding the HTML:

    python3 serve_with_logs.py

Then open the URL it prints. Logs appear in ./logs/.

Nothing is sent anywhere. This listens on 127.0.0.1 only.
"""

import http.server
import json
import os
import socketserver
import sys
from datetime import datetime
from pathlib import Path

PORT = int(os.environ.get("PORT", "8765"))
ROOT = Path(__file__).resolve().parent
LOGDIR = ROOT / "logs"
MAX_BODY = 64 * 1024 * 1024  # a full-catalogue record is ~90 KB; this is slack


def safe_name(name: str) -> str:
    """Keep the basename only, and only characters we chose to allow.

    The filename arrives from the page, so it is untrusted input: without this a
    record named ../../etc/something would escape the logs folder.
    """
    base = os.path.basename(str(name or ""))
    cleaned = "".join(c for c in base if c.isalnum() or c in "._-")
    if not cleaned or cleaned.startswith("."):
        cleaned = "ollama-log_%s.json" % datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]
    if not cleaned.endswith(".json"):
        cleaned += ".json"
    return cleaned[:200]


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.rstrip("/") == "/ping":
            self._json(200, {"ok": True, "logs": str(LOGDIR), "written": COUNT["n"]})
            return
        super().do_GET()

    def do_POST(self):
        if self.path.rstrip("/") != "/log":
            self._json(404, {"error": "post audit records to /log"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "bad Content-Length"})
            return
        if length <= 0 or length > MAX_BODY:
            self._json(413, {"error": "body empty or too large"})
            return

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
            record = payload.get("record", payload)
            name = safe_name(payload.get("filename"))
            rewrite = bool(payload.get("rewrite"))
        except (ValueError, AttributeError) as exc:
            self._json(400, {"error": "unparseable record: %s" % exc})
            return

        LOGDIR.mkdir(exist_ok=True)
        path = LOGDIR / name
        existed = path.exists()
        try:
            # Written whole, so a half-flushed file is never left behind.
            tmp = path.with_suffix(".json.part")
            tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            self._json(500, {"error": "could not write %s: %s" % (path, exc)})
            return

        if not existed:
            COUNT["n"] += 1
        verb = "updated" if (existed and rewrite) else "wrote"
        status = record.get("status", "?")
        ptok = record.get("prompt_tokens")
        trunc = " TRUNCATED" if record.get("prompt_truncated") else ""
        print(
            "  %s logs/%s  [%s%s]%s"
            % (verb, name, status, (" %s prompt tok" % ptok) if ptok else "", trunc),
            flush=True,
        )
        self._json(200, {"ok": True, "path": "logs/%s" % name})

    def log_message(self, fmt, *args):
        # Default logging prints every asset fetch; the audit lines above are
        # the only thing worth watching here.
        return


COUNT = {"n": 0}


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    pages = sorted(p.name for p in ROOT.glob("*.html"))
    LOGDIR.mkdir(exist_ok=True)
    try:
        httpd = Server(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        print("Could not bind port %d: %s" % (PORT, exc))
        print("Something else is using it. Try:  PORT=8766 python3 %s" % Path(__file__).name)
        print("If you change the port, update logSink in the page's LLM_DEFAULTS to match.")
        return 1

    print("StyleMate log sink")
    print("  serving   %s" % ROOT)
    print("  logs      %s/" % LOGDIR)
    print("  listening http://localhost:%d/  (127.0.0.1 only)" % PORT)
    for name in pages:
        print("    http://localhost:%d/%s" % (PORT, name))
    print("\nOpen a page above, search, and one JSON file per Ollama call appears in logs/.")
    print("Ctrl-C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. %d log file(s) written this run." % COUNT["n"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

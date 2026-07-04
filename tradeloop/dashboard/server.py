from __future__ import annotations

import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from tradeloop.dashboard.runs import list_runs, read_run


def _safe_run_dir(runs_dir: Path, name: str) -> Path | None:
    # only a direct child of runs_dir, no traversal
    candidate = (runs_dir / name).resolve()
    if candidate.parent != runs_dir.resolve() or not candidate.is_dir():
        return None
    return candidate


def handle_api(path: str, query: dict, runs_dir: Path) -> tuple[int, dict]:
    runs_dir = Path(runs_dir)
    if path == "/api/runs":
        return 200, {"runs": [asdict(r) for r in list_runs(runs_dir)]}
    if path == "/api/run":
        name = (query.get("dir") or [""])[0]
        d = _safe_run_dir(runs_dir, name)
        if d is None:
            return 400, {"error": "bad run dir"}
        return 200, read_run(d)
    return 404, {"error": "not found"}


def make_handler(runs_dir: Path, static_dir: Path):
    runs_dir = Path(runs_dir)
    static_dir = Path(static_dir)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body_bytes, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)

        def _json(self, status, obj):
            self._send(status, json.dumps(obj).encode("utf-8"), "application/json")

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                html = (static_dir / "index.html").read_bytes()
                return self._send(200, html, "text/html; charset=utf-8")
            if parsed.path.startswith("/api/"):
                status, body = handle_api(parsed.path, parse_qs(parsed.query), runs_dir)
                return self._json(status, body)
            self._json(404, {"error": "not found"})

        def log_message(self, *args):  # quiet
            pass

    return Handler

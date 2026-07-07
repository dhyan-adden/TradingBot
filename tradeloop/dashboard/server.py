from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from tradeloop.dashboard.portfolio import portfolio_view
from tradeloop.dashboard.runs import list_runs, read_run


def _live_prices(symbols):
    # Lazy import so the dashboard stays usable with no Kite auth; the shared
    # module-level client keeps one MCP subprocess across requests.
    from tradeloop.lib.data.kite import ltp
    return ltp(symbols)


def _starting_cash(root: Path) -> float:
    try:
        from tradeloop.lib.config import load_settings
        return float(load_settings(root / "config" / "settings.yaml").paper_starting_inr)
    except Exception:
        return 100000.0


def launch_propose(repo_root: Path, python: str = sys.executable, launcher=subprocess.Popen) -> str:
    """Start a background PROPOSE cycle on the Claude backend. Suggestions only -
    never routes. Returns "" (the run-dir name is minted inside the child; the
    page just reloads the run list to pick up the newest). `repo_root` is the git
    root (cwd for the child so `tradeloop` imports as a package)."""
    env = dict(os.environ)
    env["ZERODHA_ENABLE_DATA"] = "true"
    env.setdefault("ZERODHA_ENABLE_TRADING", "false")
    cmd = [python, "-m", "tradeloop.orchestrator", "premarket", "--backend", "claude"]
    launcher(cmd, env=env, cwd=str(Path(repo_root)))
    return ""


def _safe_run_dir(runs_dir: Path, name: str) -> Path | None:
    # only a direct child of runs_dir, no traversal
    candidate = (runs_dir / name).resolve()
    if candidate.parent != runs_dir.resolve() or not candidate.is_dir():
        return None
    return candidate


def handle_api(path: str, query: dict, runs_dir: Path, price_fn=_live_prices) -> tuple[int, dict]:
    runs_dir = Path(runs_dir)
    if path == "/api/runs":
        return 200, {"runs": [asdict(r) for r in list_runs(runs_dir)]}
    if path == "/api/run":
        name = (query.get("dir") or [""])[0]
        d = _safe_run_dir(runs_dir, name)
        if d is None:
            return 400, {"error": "bad run dir"}
        return 200, read_run(d)
    if path == "/api/portfolio":
        root = runs_dir.parent  # tradeloop/runs -> tradeloop
        return 200, portfolio_view(root / "state" / "ledger.db",
                                   _starting_cash(root), price_fn=price_fn)
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

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/run-now":
                try:
                    launch_propose(runs_dir.parent.parent)  # tradeloop/runs -> tradeloop -> repo root
                    return self._json(200, {"started": True, "dir": ""})
                except Exception as exc:  # surface, don't crash the server
                    return self._json(500, {"error": str(exc)})
            self._json(404, {"error": "not found"})

        def log_message(self, *args):  # quiet
            pass

    return Handler

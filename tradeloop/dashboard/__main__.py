from __future__ import annotations

import argparse
import os
import webbrowser
from http.server import HTTPServer
from pathlib import Path

from tradeloop.dashboard.server import make_handler

ROOT = Path(__file__).resolve().parents[1]  # tradeloop/
RUNS_DIR = ROOT / "runs"
STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_PORT = 8770


def _port_from_env() -> int:
    raw = os.environ.get("TRADELOOP_DASHBOARD_PORT")
    if not raw:
        return DEFAULT_PORT
    return int(raw)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local TradeLoop dashboard.")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Dashboard port. Defaults to TRADELOOP_DASHBOARD_PORT or {DEFAULT_PORT}.",
    )
    args = parser.parse_args(argv)
    if args.port is not None:
        return args
    try:
        args.port = _port_from_env()
    except ValueError:
        parser.error("TRADELOOP_DASHBOARD_PORT must be an integer")
    return args


def main(port: int = 8770) -> None:
    handler = make_handler(RUNS_DIR, STATIC_DIR)
    server = HTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"TradeLoop dashboard at {url}  (Ctrl-C to stop)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    args = parse_args()
    main(port=args.port)

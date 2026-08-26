from __future__ import annotations

import webbrowser
from http.server import HTTPServer
from pathlib import Path

from tradeloop.dashboard.server import make_handler

ROOT = Path(__file__).resolve().parents[1]  # tradeloop/
RUNS_DIR = ROOT / "runs"
STATIC_DIR = Path(__file__).resolve().parent / "static"


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
    main()

#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

from tradeloop.lib.ops.alerts import record_alert

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind")
    parser.add_argument("message")
    args = parser.parse_args()
    path = record_alert(ROOT, args.kind, args.message)
    print(f"tradeloop_alert_recorded={path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

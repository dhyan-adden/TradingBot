#!/usr/bin/env python
import argparse
import sys
from datetime import date
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tradeloop.lib.broker.router import live_enabled, live_promotion_ready
from tradeloop.lib.config import load_settings
from tradeloop.lib.risk.circuit_breaker import kill_switch_active
from tradeloop.lib.util.holidays import is_nse_holiday


ROOT = Path(__file__).resolve().parents[1]


def verify(mode: str, check_live_readiness: bool = False) -> int:
    settings = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")) or {}
    if mode not in settings.get("modes", {}):
        raise ValueError(f"unknown mode: {mode}")
    if is_nse_holiday(date.today()):
        print("tradeloop_setup=SKIP reason=nse_holiday")
        return 0
    if kill_switch_active(ROOT):
        print("tradeloop_setup=HALTED reason=kill_switch")
        return 0
    if check_live_readiness or live_enabled():
        settings = load_settings(ROOT / "config" / "settings.yaml")
        if not live_promotion_ready(ROOT, settings):
            print("tradeloop_setup=LIVE_NOT_READY")
            return 2
    print(f"tradeloop_setup=OK mode={mode}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="premarket", choices=["premarket", "intraday", "postclose", "adhoc"])
    parser.add_argument("--check-live-readiness", action="store_true")
    args = parser.parse_args()
    return verify(args.mode, args.check_live_readiness)


if __name__ == "__main__":
    raise SystemExit(main())

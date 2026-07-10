#!/usr/bin/env python
import argparse
import importlib
import json as _json
import subprocess
import sys
from datetime import date, datetime, timezone
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


def claude_authenticated(cli: str = "claude", timeout: float = 15.0) -> bool:
    """True when the claude CLI answers a trivial prompt (a proxy for a live
    subscription login on this machine). Any nonzero exit, error, or timeout
    reads as not-authenticated so the cycle fails loudly at prepare, not mid-DAG."""
    try:
        proc = subprocess.run(
            [cli, "-p", "--model", "haiku", "--max-turns", "1"],
            input="reply with OK", capture_output=True, text=True, timeout=timeout)
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def verify(mode: str, check_live_readiness: bool = False, backend: str | None = None) -> int:
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
    if backend == "claude" and not claude_authenticated():
        print("tradeloop_setup=CLAUDE_AUTH_MISSING")
        return 4
    print(f"tradeloop_setup=OK mode={mode}")
    return 0


def check_imports() -> list:
    missing = []
    for module in ("yaml", "pandas", "pydantic"):
        try:
            importlib.import_module(module)
        except Exception:
            missing.append(module)
    return missing


def source_health(root: Path, max_age_hours: float = 26.0) -> list:
    report = root / "reports" / "source_health.json"
    if not report.exists():
        return ["_no_source_health_report_"]
    data = _json.loads(report.read_text(encoding="utf-8")) or {}
    now = datetime.now(timezone.utc)
    stale = []
    for source, last_success in data.items():
        try:
            ts = datetime.fromisoformat(str(last_success))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            stale.append(source)
            continue
        if (now - ts).total_seconds() > max_age_hours * 3600:
            stale.append(source)
    return stale


def health(root: Path) -> int:
    missing = check_imports()
    stale = source_health(root)
    if missing or stale:
        print(f"tradeloop_health=FAIL reason=imports:{','.join(missing) or '-'} sources:{','.join(stale) or '-'}")
        return 3
    print("tradeloop_health=OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="premarket", choices=["premarket", "intraday", "postclose", "adhoc"])
    parser.add_argument("--check-live-readiness", action="store_true")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--backend", default=None, choices=["openrouter", "claude"])
    args = parser.parse_args()
    if args.health:
        return health(ROOT)
    return verify(args.mode, args.check_live_readiness, backend=args.backend)


if __name__ == "__main__":
    raise SystemExit(main())

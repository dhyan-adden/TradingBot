#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tradeloop.lib.ops.alerts import record_alert
from tradeloop.lib.util.holidays import is_nse_holiday
from tradeloop.lib.util.ist_clock import IST

ROOT = Path(__file__).resolve().parents[1]
SCHEDULES = {
    "premarket": time(8, 0),
    "intraday": time(14, 0),
    "postclose": time(16, 0),
}


def _run_date(name: str, mode: str):
    suffix = f"_{mode}"
    if not name.endswith(suffix):
        return None
    try:
        return datetime.strptime(name.removesuffix(suffix), "%Y-%m-%d_%H%M").date()
    except ValueError:
        return None


def completed_modes(root: Path, day) -> set[str]:
    runs_dir = Path(root) / "runs"
    if not runs_dir.is_dir():
        return set()
    out = set()
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        for mode in SCHEDULES:
            if _run_date(run_dir.name, mode) == day:
                out.add(mode)
    return out


def missed_modes(root: Path, now: datetime | None = None,
                 grace_minutes: int = 30) -> list[str]:
    current = (now or datetime.now(IST)).astimezone(IST)
    day = current.date()
    if is_nse_holiday(day):
        return []
    done = completed_modes(root, day)
    missed = []
    for mode, scheduled_at in SCHEDULES.items():
        due = datetime.combine(day, scheduled_at, IST) + timedelta(minutes=grace_minutes)
        if current >= due and mode not in done:
            missed.append(mode)
    return missed


def _already_alerted(root: Path, day: str, mode: str) -> bool:
    path = Path(root) / "reports" / "alerts.jsonl"
    if not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        details = rec.get("details") or {}
        if (rec.get("kind") == "missed_scheduled_cycle"
                and details.get("date") == day and details.get("mode") == mode):
            return True
    return False


def record_missed_alerts(root: Path, missed: list[str], now: datetime | None = None) -> None:
    current = (now or datetime.now(IST)).astimezone(IST)
    day = current.date().isoformat()
    for mode in missed:
        if _already_alerted(root, day, mode):
            continue
        record_alert(root, "missed_scheduled_cycle", f"missed scheduled {mode} cycle",
                     {"date": day, "mode": mode}, now=current)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    missed = missed_modes(args.root)
    if missed:
        if not args.dry_run:
            record_missed_alerts(args.root, missed)
        print("schedule_health=FAIL missed=" + ",".join(missed))
        return 2
    print("schedule_health=OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

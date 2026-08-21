import json
from datetime import datetime

from tradeloop.lib.util.ist_clock import IST
from tradeloop.scripts.check_schedule_health import missed_modes, record_missed_alerts


def test_schedule_health_flags_due_missing_cycle(tmp_path):
    root = tmp_path / "tradeloop"
    (root / "runs").mkdir(parents=True)

    missed = missed_modes(root, datetime(2026, 8, 18, 9, 0, tzinfo=IST))

    assert missed == ["premarket"]


def test_schedule_health_ignores_completed_cycle(tmp_path):
    root = tmp_path / "tradeloop"
    run_dir = root / "runs" / "2026-08-18_0801_premarket"
    run_dir.mkdir(parents=True)

    missed = missed_modes(root, datetime(2026, 8, 18, 9, 0, tzinfo=IST))

    assert missed == []


def test_missed_cycle_alert_is_deduped_per_day_and_mode(tmp_path):
    root = tmp_path / "tradeloop"
    missed = ["premarket"]
    now = datetime(2026, 8, 18, 9, 0, tzinfo=IST)

    record_missed_alerts(root, missed, now=now)
    record_missed_alerts(root, missed, now=now)

    lines = (root / "reports" / "alerts.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert len(records) == 1
    assert records[0]["kind"] == "missed_scheduled_cycle"
    assert records[0]["details"] == {"date": "2026-08-18", "mode": "premarket"}

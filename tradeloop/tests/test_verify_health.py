import json
from datetime import datetime, timedelta, timezone

import tradeloop.scripts.verify_setup as vs


def test_check_imports_all_present():
    assert vs.check_imports() == []  # yaml/pandas/pydantic declared in P0 packaging


def test_source_health_flags_stale_and_missing(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    (reports / "source_health.json").write_text(json.dumps({"google_news": fresh, "nse_bse": old}), encoding="utf-8")
    stale = vs.source_health(tmp_path, max_age_hours=26.0)
    assert "nse_bse" in stale
    assert "google_news" not in stale


def test_source_health_missing_file_is_unhealthy(tmp_path):
    assert vs.source_health(tmp_path) == ["_no_source_health_report_"]


def test_source_health_malformed_file_is_unhealthy(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "source_health.json").write_text("{broken", encoding="utf-8")
    assert vs.source_health(tmp_path) == ["_malformed_source_health_report_"]


def test_source_health_empty_file_is_unhealthy(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "source_health.json").write_text("{}", encoding="utf-8")
    assert vs.source_health(tmp_path) == ["_empty_source_health_report_"]


def test_health_returns_3_when_source_missing(tmp_path, capsys):
    assert vs.health(tmp_path) == 3
    assert "FAIL" in capsys.readouterr().out

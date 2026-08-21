import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tradeloop.dashboard.server import handle_api
from tradeloop.dashboard.status import dashboard_status

ROOT = Path(__file__).resolve().parents[2]


def _root(tmp_path):
    root = tmp_path / "tradeloop"
    (root / "config").mkdir(parents=True)
    (root / "reports").mkdir()
    (root / "runs").mkdir()
    shutil.copy(ROOT / "config" / "settings.yaml", root / "config" / "settings.yaml")
    (root / "reports" / "source_health.json").write_text(
        json.dumps({"google_news": datetime.now(timezone.utc).isoformat()}),
        encoding="utf-8",
    )
    return root


def test_dashboard_status_surfaces_live_promotion_and_source_health(tmp_path):
    root = _root(tmp_path)

    status = dashboard_status(root)

    assert status["source_health"] == {"ok": True, "stale_sources": []}
    assert status["live_promotion"]["ready"] is False
    assert "no ledger" in status["live_promotion"]["reasons"][0]
    assert status["latest_run"] is None


def test_dashboard_status_summarizes_latest_run_gates(tmp_path):
    root = _root(tmp_path)
    run_dir = root / "runs" / "2026-07-04_0900_premarket"
    run_dir.mkdir()
    (run_dir / "orders.json").write_text(json.dumps({"orders": [{"symbol": "TCS"}]}), encoding="utf-8")
    (run_dir / "fills.json").write_text(json.dumps([]), encoding="utf-8")
    (run_dir / "controls.json").write_text(json.dumps({"deficiencies": []}), encoding="utf-8")

    latest = dashboard_status(root)["latest_run"]

    assert latest["dir"] == "2026-07-04_0900_premarket"
    assert latest["proposed_orders"] == 1
    assert latest["approval"] == "missing_or_invalid"
    assert latest["routed"] is False
    assert latest["controls"] == "clean"
    assert latest["live_reconciliation"] == "missing"


def test_api_status_route(tmp_path):
    root = _root(tmp_path)

    status, body = handle_api("/api/status", {}, root / "runs")

    assert status == 200
    assert body["source_health"]["ok"] is True

import json
from pathlib import Path

from tradeloop.dashboard.server import handle_api


def _seed(tmp_path):
    d = tmp_path / "2026-07-04_0900_premarket"
    d.mkdir(parents=True)
    (d / "10_news.json").write_text(json.dumps({"names_in_play": []}))
    (d / "orders.json").write_text(json.dumps({"orders": [], "held": []}))
    return tmp_path


def test_api_runs_lists(tmp_path):
    runs_dir = _seed(tmp_path)
    status, body = handle_api("/api/runs", {}, runs_dir)
    assert status == 200
    assert body["runs"][0]["dir_name"] == "2026-07-04_0900_premarket"


def test_api_run_reads_one(tmp_path):
    runs_dir = _seed(tmp_path)
    status, body = handle_api("/api/run", {"dir": ["2026-07-04_0900_premarket"]}, runs_dir)
    assert status == 200
    assert body["dir"] == "2026-07-04_0900_premarket"
    assert "stages" in body


def test_api_run_rejects_path_traversal(tmp_path):
    runs_dir = _seed(tmp_path)
    status, _ = handle_api("/api/run", {"dir": ["../../etc"]}, runs_dir)
    assert status == 400


def test_api_unknown_route_404(tmp_path):
    status, _ = handle_api("/api/nope", {}, tmp_path)
    assert status == 404

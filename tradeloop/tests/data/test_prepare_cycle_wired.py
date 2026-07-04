from pathlib import Path

from tradeloop.scripts import prepare_cycle


def test_prepare_calls_ingest(monkeypatch, tmp_path):
    # kills a regression where prepare_cycle keeps writing the empty NewsExtraction()/[] renderers
    called = {}

    def fake_run(as_of, run_dir, config_dir):
        called["run_dir"] = Path(run_dir)
        called["config_dir"] = Path(config_dir)
        (Path(run_dir) / "01_news_raw.md").write_text("# Raw News\n\n### RELIANCE\n- [nid] hit\n")
        (Path(run_dir) / "02_setups_raw.md").write_text("# Raw Technical Setups\n")
        from tradeloop.lib.data.snapshot import Snapshot
        return Snapshot(run_dir=Path(run_dir), snapshot_hash="h", news_ids={"nid"}, news_available=True)

    (tmp_path / "config").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text("capital:\n  paper_starting_inr: 100000\n")
    monkeypatch.setattr(prepare_cycle, "ingest_run", fake_run)
    # stub context rendering that reads settings/memory so the test is hermetic
    monkeypatch.setattr(prepare_cycle, "empty_state_from_settings", lambda p: object())
    monkeypatch.setattr(prepare_cycle, "render_context", lambda s, m, mac: "# Context\n")

    run_dir = prepare_cycle.prepare("premarket", root=tmp_path)
    assert "RELIANCE" in (run_dir / "01_news_raw.md").read_text()
    assert called["run_dir"] == run_dir
    assert called["config_dir"] == tmp_path / "config"


def test_prepare_degrades_not_aborts_on_ingest_failure(monkeypatch, tmp_path):
    # kills a regression where an ingest exception crashes the cycle instead of degrading loudly
    def boom_run(as_of, run_dir, config_dir):
        raise RuntimeError("all sources down")

    (tmp_path / "config").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text("capital:\n  paper_starting_inr: 100000\n")
    monkeypatch.setattr(prepare_cycle, "ingest_run", boom_run)
    monkeypatch.setattr(prepare_cycle, "empty_state_from_settings", lambda p: object())
    monkeypatch.setattr(prepare_cycle, "render_context", lambda s, m, mac: "# Context\n")

    run_dir = prepare_cycle.prepare("premarket", root=tmp_path)
    assert "NO NEWS DATA" in (run_dir / "01_news_raw.md").read_text()
    assert (run_dir / "02_setups_raw.md").exists()
    assert "all sources down" in (run_dir / "ingest_error.txt").read_text()

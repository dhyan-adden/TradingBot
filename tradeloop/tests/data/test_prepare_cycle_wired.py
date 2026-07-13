from pathlib import Path

from tradeloop.scripts import prepare_cycle


def test_prepare_calls_ingest(monkeypatch, tmp_path):
    # kills a regression where prepare_cycle keeps writing the empty NewsExtraction()/[] renderers
    called = {}

    def fake_run(as_of, run_dir, config_dir, kite_client=None, source_health_root=None):
        called["run_dir"] = Path(run_dir)
        called["config_dir"] = Path(config_dir)
        called["kite_client"] = kite_client
        called["source_health_root"] = source_health_root
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
    # wiring guard: prepare MUST pass source_health_root=base, else the health check's
    # source_health.json is never written and the deploy check goes permanently red.
    assert called["source_health_root"] == tmp_path


def test_prepare_degrades_not_aborts_on_ingest_failure(monkeypatch, tmp_path):
    # kills a regression where an ingest exception crashes the cycle instead of degrading loudly
    def boom_run(as_of, run_dir, config_dir, kite_client=None, source_health_root=None):
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


def _hermetic(monkeypatch, tmp_path, captured):
    (tmp_path / "config").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text("capital:\n  paper_starting_inr: 100000\n")

    def fake_run(as_of, run_dir, config_dir, kite_client=None, source_health_root=None):
        captured["kite_client"] = kite_client
        from tradeloop.lib.data.snapshot import Snapshot
        return Snapshot(run_dir=Path(run_dir), snapshot_hash="h", news_ids=set(), news_available=False)

    monkeypatch.setattr(prepare_cycle, "ingest_run", fake_run)
    monkeypatch.setattr(prepare_cycle, "empty_state_from_settings", lambda p: object())
    monkeypatch.setattr(prepare_cycle, "render_context", lambda s, m, mac: "# Context\n")


def test_scan_dormant_when_flag_unset(monkeypatch, tmp_path):
    # no ZERODHA_ENABLE_DATA -> no live client -> scan stays dormant (never spawns the MCP)
    captured = {}
    _hermetic(monkeypatch, tmp_path, captured)
    monkeypatch.delenv("ZERODHA_ENABLE_DATA", raising=False)
    prepare_cycle.prepare("premarket", root=tmp_path)
    assert captured["kite_client"] is None


def test_scan_activates_when_flag_set(monkeypatch, tmp_path):
    # ZERODHA_ENABLE_DATA=true -> prepare constructs a KiteClient and passes it to ingest
    captured = {}
    _hermetic(monkeypatch, tmp_path, captured)
    sentinel = object()
    monkeypatch.setattr(prepare_cycle, "KiteClient", lambda: sentinel)
    monkeypatch.setenv("ZERODHA_ENABLE_DATA", "true")
    prepare_cycle.prepare("premarket", root=tmp_path)
    assert captured["kite_client"] is sentinel


def test_injected_client_overrides_flag(monkeypatch, tmp_path):
    # an explicitly injected client is used as-is (the flag path only fills a None)
    captured = {}
    _hermetic(monkeypatch, tmp_path, captured)
    monkeypatch.delenv("ZERODHA_ENABLE_DATA", raising=False)
    injected = object()
    prepare_cycle.prepare("premarket", root=tmp_path, kite_client=injected)
    assert captured["kite_client"] is injected


def test_portfolio_state_takes_latest_stop_update(tmp_path):
    from tradeloop.lib.audit.ledger import Ledger, ORDER_FILLED, STOP_UPDATED

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text("capital:\n  paper_starting_inr: 100000\n")
    (tmp_path / "state").mkdir()
    led = Ledger(tmp_path / "state" / "ledger.db")
    led.append({"type": ORDER_FILLED, "order_id": "X1", "symbol": "HDFCBANK",
                "side": "BUY", "quantity": 30, "fill_price": 830.62,
                "product": "CNC", "hard_stop": 807.24})
    led.append({"type": STOP_UPDATED, "symbol": "HDFCBANK", "hard_stop": 820.0})
    state = prepare_cycle._portfolio_state(tmp_path)
    assert state.hard_stops["HDFCBANK"] == 820.0

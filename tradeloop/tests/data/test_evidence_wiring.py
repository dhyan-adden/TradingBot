import json
from datetime import date

from tradeloop import orchestrator
from tradeloop.lib.data.snapshot import freeze
from tradeloop.lib.data.tickers import TaggedStory


def _fresh_root(tmp_path):
    import shutil
    from pathlib import Path
    root = tmp_path / "tradeloop"
    (root / "config").mkdir(parents=True)
    (root / "state").mkdir()
    src = Path(__file__).resolve().parents[2]
    shutil.copy(src / "config" / "settings.yaml", root / "config" / "settings.yaml")
    shutil.copy(src / "config" / "universe.yaml", root / "config" / "universe.yaml")
    return root


def _freeze_known_story(run_dir, news_id="knownid00001"):
    story = TaggedStory("RELIANCE", "Reliance posts record profit", "http://x",
                         "google_news_generic", "tier_C", "earnings", news_id, 1.0)
    freeze([story], [], [], run_dir)


def _valid_orders_json(run_dir):
    (run_dir / "orders.json").write_text(json.dumps({"orders": [
        {"ticker": "RELIANCE", "side": "BUY", "quantity": 20, "price": 1000, "hard_stop": 950.0},
    ]}), encoding="utf-8")


def test_known_cited_news_id_reaches_awaiting_approval(monkeypatch, tmp_path):
    # kills a false-positive block: a cycle citing a REAL news_id from its own
    # frozen snapshot must be allowed through to approval.
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))

    def fake_prepare(mode, request="", root=None):
        run_dir = root / "runs" / f"known_{mode}"
        run_dir.mkdir(parents=True, exist_ok=True)
        _freeze_known_story(run_dir)
        return run_dir

    def fake_reason(run_dir, mode, agent, timeout, **kwargs):
        _valid_orders_json(run_dir)
        (run_dir / "20_bull.json").write_text(json.dumps(
            {"evidence": ["knownid00001"]}), encoding="utf-8")
        return 0

    monkeypatch.setattr(orchestrator, "_prepare", fake_prepare)
    monkeypatch.setattr(orchestrator, "_run_reasoning", fake_reason)
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 0


def test_phantom_cited_news_id_blocks_with_evidence_invalid(monkeypatch, tmp_path, capsys):
    # kills the core bug this task exists to prevent: reasoning that cites a
    # news_id absent from its own frozen snapshot (fabricated evidence) must
    # be blocked at propose time, not silently approved.
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))

    def fake_prepare(mode, request="", root=None):
        run_dir = root / "runs" / f"phantom_{mode}"
        run_dir.mkdir(parents=True, exist_ok=True)
        _freeze_known_story(run_dir)
        return run_dir

    def fake_reason(run_dir, mode, agent, timeout, **kwargs):
        _valid_orders_json(run_dir)
        (run_dir / "20_bull.json").write_text(json.dumps(
            {"evidence": ["phantomid0001"]}), encoding="utf-8")
        return 0

    monkeypatch.setattr(orchestrator, "_prepare", fake_prepare)
    monkeypatch.setattr(orchestrator, "_run_reasoning", fake_reason)
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 1
    out = capsys.readouterr().out
    assert "EVIDENCE_INVALID" in out


def test_no_snapshot_on_disk_skips_check(monkeypatch, tmp_path):
    # kills a regression that would break existing monkeypatched-_prepare tests
    # (no frozen snapshot dir): load_snapshot returns None -> check is skipped.
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))

    def fake_prepare(mode, request="", root=None):
        run_dir = root / "runs" / f"nosnap_{mode}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def fake_reason(run_dir, mode, agent, timeout, **kwargs):
        _valid_orders_json(run_dir)
        (run_dir / "20_bull.json").write_text(json.dumps(
            {"evidence": ["anything0001"]}), encoding="utf-8")
        return 0

    monkeypatch.setattr(orchestrator, "_prepare", fake_prepare)
    monkeypatch.setattr(orchestrator, "_run_reasoning", fake_reason)
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 0

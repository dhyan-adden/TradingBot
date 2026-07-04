import json
import shutil
from datetime import date
from pathlib import Path

from tradeloop import orchestrator
from tradeloop.lib.data.snapshot import freeze
from tradeloop.lib.data.tickers import TaggedStory
from tradeloop.lib.ta.scanner import SetupScan


def _fresh_root(tmp_path):
    root = tmp_path / "tradeloop"
    (root / "config").mkdir(parents=True)
    (root / "state").mkdir()
    src = Path(__file__).resolve().parents[2]
    shutil.copy(src / "config" / "settings.yaml", root / "config" / "settings.yaml")
    shutil.copy(src / "config" / "universe.yaml", root / "config" / "universe.yaml")
    return root


def _freeze_setup(run_dir):
    story = TaggedStory("HDFCBANK", "HDFC Q1 update", "http://x",
                        "google_news_generic", "tier_A", "earnings", "knownid00001", 1.0)
    setup = SetupScan(ticker="HDFCBANK", setup_type="20d_breakout", cleanliness_score=6.0,
                      entry_zone="801.05", stop_zone="779.48", target_zone="829.81/844.20",
                      volume_context="volume_normal")
    freeze([story], [], [setup], run_dir)


def _orders(run_dir, price, hard_stop):
    (run_dir / "orders.json").write_text(json.dumps({"orders": [
        {"ticker": "HDFCBANK", "side": "BUY", "quantity": 20,
         "price": price, "hard_stop": hard_stop, "evidence": ["knownid00001"]},
    ]}), encoding="utf-8")


def _wire(monkeypatch, root, price, hard_stop, tag):
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))

    def fake_prepare(mode, request="", root=None):
        run_dir = root / "runs" / f"{tag}_{mode}"
        run_dir.mkdir(parents=True, exist_ok=True)
        _freeze_setup(run_dir)
        return run_dir

    def fake_reason(run_dir, mode, agent, timeout):
        _orders(run_dir, price, hard_stop)
        return 0

    monkeypatch.setattr(orchestrator, "_prepare", fake_prepare)
    monkeypatch.setattr(orchestrator, "_run_reasoning", fake_reason)


def test_order_matching_scan_reaches_awaiting_approval(monkeypatch, tmp_path):
    root = _fresh_root(tmp_path)
    _wire(monkeypatch, root, price=801.05, hard_stop=779.48, tag="grounded")
    assert orchestrator.run_cycle("premarket", root=root) == 0


def test_news_anchored_order_blocked_with_price_ungrounded(monkeypatch, tmp_path, capsys):
    # the core bug: entry/stop invented from a stale news headline (1680 vs real
    # 801) must be blocked at propose time, deterministically.
    root = _fresh_root(tmp_path)
    _wire(monkeypatch, root, price=1680.0, hard_stop=1640.0, tag="ungrounded")
    assert orchestrator.run_cycle("premarket", root=root) == 1
    assert "PRICE_UNGROUNDED" in capsys.readouterr().out

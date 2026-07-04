import json
from datetime import datetime
from pathlib import Path

from tradeloop.lib.data import ingest
from tradeloop.lib.data.tickers import TaggedStory
from tradeloop.lib.ta.scanner import SetupScan


def _setup(ticker, score):
    return SetupScan(ticker=ticker, setup_type="20d_breakout", cleanliness_score=score,
                     entry_zone="100.0", stop_zone="95.0", target_zone="110.0/115.0",
                     volume_context="ok")


def test_ingest_caps_downstream_and_dumps_full_scan(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    # 3 fake setups; cap keeps top 2 by score downstream, all 3 to disk
    fake = [_setup("AAA", 9.0), _setup("BBB", 8.0), _setup("CCC", 7.0)]
    monkeypatch.setattr(ingest, "scan_universe", lambda *a, **k: sorted(
        fake, key=lambda s: s.cleanliness_score, reverse=True))
    monkeypatch.setattr(ingest, "load_universe", lambda *a, **k: ["AAA", "BBB", "CCC"])
    monkeypatch.setattr(ingest, "_collect_news", lambda *a, **k: ([], []))

    snap = ingest.run(datetime(2026, 7, 6, 9, 0), run_dir=run_dir,
                      kite_client=object(), config_dir=Path("tradeloop/config"),
                      max_setups_downstream=2)

    # downstream (frozen snapshot + trader input) sees only the top 2
    assert {s.ticker for s in snap.setups} == {"AAA", "BBB"}
    # full scan dumped to disk with all 3
    dumped = [json.loads(l) for l in (run_dir / "full_scan.jsonl").read_text().splitlines()]
    assert {d["ticker"] for d in dumped} == {"AAA", "BBB", "CCC"}


def test_downstream_cap_prioritises_news_backed_over_cleaner_chart(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    # NEWSY has the WORST chart score but a real news catalyst; CLEAN1/CLEAN2 are
    # cleaner charts with no news. With top_n=2, NEWSY must survive and the cleanest
    # non-news (CLEAN1) fills the second slot; CLEAN2 is dropped.
    setups = [_setup("CLEAN1", 9.0), _setup("CLEAN2", 8.0), _setup("NEWSY", 3.0)]
    monkeypatch.setattr(ingest, "scan_universe", lambda *a, **k: list(setups))
    monkeypatch.setattr(ingest, "load_universe", lambda *a, **k: ["CLEAN1", "CLEAN2", "NEWSY"])
    monkeypatch.setattr(ingest, "_collect_news", lambda *a, **k: (["x"], []))
    story = TaggedStory(ticker="NEWSY", title="NEWSY beats Q1", url="http://x",
                        source="feed", tier="tier_A", category="earnings",
                        news_id="abc123", confidence=1.0)
    monkeypatch.setattr(ingest, "extract", lambda *a, **k: [story])

    snap = ingest.run(datetime(2026, 7, 6, 9, 0), run_dir=run_dir,
                      kite_client=object(), config_dir=Path("tradeloop/config"),
                      max_setups_downstream=2)

    assert {s.ticker for s in snap.setups} == {"NEWSY", "CLEAN1"}

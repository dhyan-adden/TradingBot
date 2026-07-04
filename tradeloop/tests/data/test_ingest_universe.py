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


def test_overflow_cut_blends_news_and_chart_not_news_override(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    # Overflow tiebreak (top_n=2 forces a cut). News is a WEIGHTED factor (+2.0), not an
    # override: NEWSY (chart 6.0 + news 2.0 = 8.0) beats CLEAN_MID (7.0, no news), but a
    # weak news chart does NOT beat a much cleaner one - CLEAN_TOP (9.0) still wins.
    setups = [_setup("CLEAN_TOP", 9.0), _setup("CLEAN_MID", 7.0), _setup("NEWSY", 6.0)]
    monkeypatch.setattr(ingest, "scan_universe", lambda *a, **k: list(setups))
    monkeypatch.setattr(ingest, "load_universe", lambda *a, **k: ["CLEAN_TOP", "CLEAN_MID", "NEWSY"])
    monkeypatch.setattr(ingest, "_collect_news", lambda *a, **k: (["x"], []))
    story = TaggedStory(ticker="NEWSY", title="NEWSY beats Q1", url="http://x",
                        source="feed", tier="tier_A", category="earnings",
                        news_id="abc123", confidence=1.0)
    monkeypatch.setattr(ingest, "extract", lambda *a, **k: [story])

    snap = ingest.run(datetime(2026, 7, 6, 9, 0), run_dir=run_dir,
                      kite_client=object(), config_dir=Path("tradeloop/config"),
                      max_setups_downstream=2)

    # blended scores: CLEAN_TOP 9.0, NEWSY 8.0, CLEAN_MID 7.0 -> top 2 kept
    assert {s.ticker for s in snap.setups} == {"CLEAN_TOP", "NEWSY"}

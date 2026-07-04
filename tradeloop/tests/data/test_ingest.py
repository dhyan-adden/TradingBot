from datetime import date, datetime
from pathlib import Path

from tradeloop.lib.data import ingest
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.ticker_master import load_master

TM = load_master(Path("tradeloop/config/universe.yaml"))


class NoKite:
    def historical(self, *a, **k):
        return []


def test_run_with_news_freezes_and_renders(tmp_path, monkeypatch):
    # kills a regression where fetched stories never reach the frozen snapshot / rendered md
    def fake_news(http, master, cfg):
        stories = [RawItem("nid000000001", "Reliance posts record profit",
                           "http://x", "google_news_generic", "tier_C", "2026-07-02")]
        return stories, []  # (all_items, macro_items)

    monkeypatch.setattr(ingest, "_collect_news", fake_news)
    snap = ingest.run(datetime(2026, 7, 2), TM.symbols(), max_fetch=5, run_dir=tmp_path,
                      kite_client=NoKite(), master=TM)
    assert snap.news_available is True
    assert "nid000000001" in snap.news_ids
    body = (tmp_path / "01_news_raw.md").read_text()
    assert "RELIANCE" in body
    assert (tmp_path / "snapshot" / "snapshot_hash.txt").exists()


def test_run_total_news_failure_is_loud_not_blank(tmp_path, monkeypatch):
    # kills a regression where a total news outage silently renders an empty (not loud) artifact
    monkeypatch.setattr(ingest, "_collect_news", lambda http, master, cfg: ([], []))
    snap = ingest.run(datetime(2026, 7, 2), TM.symbols(), max_fetch=5, run_dir=tmp_path,
                      kite_client=NoKite(), master=TM)
    assert snap.news_available is False
    assert "NO NEWS DATA" in (tmp_path / "01_news_raw.md").read_text()


def test_run_symbols_optional_defaults_to_master_symbols(tmp_path, monkeypatch):
    # kills a regression against V2: symbols must be optional, defaulting to master.symbols()
    monkeypatch.setattr(ingest, "_collect_news", lambda http, master, cfg: ([], []))
    snap = ingest.run(datetime(2026, 7, 2), run_dir=tmp_path, kite_client=NoKite(), master=TM)
    assert snap.run_dir == tmp_path


def test_run_requires_run_dir():
    # kills a regression where run_dir silently defaults instead of failing loudly
    try:
        ingest.run(datetime(2026, 7, 2), master=TM)
    except AssertionError:
        pass
    else:
        raise AssertionError("ingest.run should assert when run_dir is missing")

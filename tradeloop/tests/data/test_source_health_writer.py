import json
from datetime import datetime, timezone
from pathlib import Path

from tradeloop.lib.data import ingest
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.ticker_master import load_master

TM = load_master(Path("tradeloop/config/universe.yaml"))


class NoKite:
    def historical(self, *a, **k):
        return []


def _item(source):
    return RawItem("nid000000001", "headline", "http://x", source, "tier_C", "2026-07-06")


def test_writer_stamps_producing_sources_then_merges(tmp_path, monkeypatch):
    # config_dir=tmp_path keeps this hermetic (real config is source=full_nse -> 2400+ scan)
    health_root = tmp_path / "health_root"
    report = health_root / "reports" / "source_health.json"
    as_of = datetime(2026, 7, 6, 8, 30, tzinfo=timezone.utc)

    monkeypatch.setattr(ingest, "_collect_news",
                        lambda http, master, cfg: ([_item("google_news"), _item("nse_bse")], []))
    ingest.run(as_of, run_dir=tmp_path / "run1", config_dir=tmp_path,
               kite_client=NoKite(), master=TM, source_health_root=health_root)
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["google_news"] == as_of.isoformat()
    assert data["nse_bse"] == as_of.isoformat()

    # a later run producing only reddit MERGES: reddit stamped, prior sources preserved
    later = datetime(2026, 7, 7, 8, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(ingest, "_collect_news",
                        lambda http, master, cfg: ([_item("reddit")], []))
    ingest.run(later, run_dir=tmp_path / "run2", config_dir=tmp_path,
               kite_client=NoKite(), master=TM, source_health_root=health_root)
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["reddit"] == later.isoformat()
    assert data["google_news"] == as_of.isoformat()
    assert data["nse_bse"] == as_of.isoformat()

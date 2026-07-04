import json
from datetime import date

from tradeloop.lib.data.universe import load_universe


class FakeKite:
    def __init__(self, symbols):
        self._symbols = symbols
        self.called = 0

    def instruments(self, exchange="NSE", instrument_type="EQ"):
        self.called += 1
        return {s: i for i, s in enumerate(self._symbols, start=1)}


def _yaml(tmp_path):
    p = tmp_path / "universe.yaml"
    p.write_text("symbols:\n  - symbol: RELIANCE\n  - symbol: TCS\nwatchlist: []\n")
    return p


def test_fetches_and_writes_cache_when_missing(tmp_path):
    cache = tmp_path / "universe_cache.json"
    kite = FakeKite(["RELIANCE", "SBIN", "INFY"])
    syms = load_universe(kite, cache, _yaml(tmp_path), now=date(2026, 7, 6))
    assert set(syms) == {"RELIANCE", "SBIN", "INFY"}
    assert kite.called == 1
    assert json.loads(cache.read_text())["fetched"] == "2026-07-06"


def test_reads_fresh_cache_without_calling_kite(tmp_path):
    cache = tmp_path / "universe_cache.json"
    cache.write_text(json.dumps({"fetched": "2026-07-05", "symbols": ["AAA", "BBB"]}))
    kite = FakeKite(["RELIANCE"])
    syms = load_universe(kite, cache, _yaml(tmp_path), now=date(2026, 7, 6))
    assert syms == ["AAA", "BBB"]
    assert kite.called == 0  # cache fresh (1 day old)


def test_stale_cache_triggers_refetch(tmp_path):
    cache = tmp_path / "universe_cache.json"
    cache.write_text(json.dumps({"fetched": "2026-06-01", "symbols": ["OLD"]}))
    kite = FakeKite(["RELIANCE", "SBIN"])
    syms = load_universe(kite, cache, _yaml(tmp_path), max_age_days=7, now=date(2026, 7, 6))
    assert set(syms) == {"RELIANCE", "SBIN"}
    assert kite.called == 1


def test_falls_back_to_yaml_when_kite_errors(tmp_path):
    cache = tmp_path / "universe_cache.json"

    class Broken:
        def instruments(self, *a, **k):
            raise RuntimeError("kite down")

    syms = load_universe(Broken(), cache, _yaml(tmp_path), now=date(2026, 7, 6))
    assert set(syms) == {"RELIANCE", "TCS"}  # from yaml


def test_no_kite_uses_yaml(tmp_path):
    cache = tmp_path / "universe_cache.json"
    syms = load_universe(None, cache, _yaml(tmp_path), now=date(2026, 7, 6))
    assert set(syms) == {"RELIANCE", "TCS"}


def test_truncates_to_max_symbols(tmp_path):
    cache = tmp_path / "universe_cache.json"
    kite = FakeKite([f"S{i}" for i in range(100)])
    syms = load_universe(kite, cache, _yaml(tmp_path), max_symbols=10, now=date(2026, 7, 6))
    assert len(syms) == 10

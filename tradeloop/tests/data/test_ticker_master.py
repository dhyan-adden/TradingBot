from pathlib import Path

from tradeloop.lib.data.ticker_master import load_master

UNIVERSE = Path("tradeloop/config/universe.yaml")


def test_symbols_and_sector():
    tm = load_master(UNIVERSE)
    assert "RELIANCE" in tm.symbols()
    assert tm.sector_of("RELIANCE") == "Energy"


def test_isin_index():
    tm = load_master(UNIVERSE)
    rec = tm.by_isin("INE002A01018")
    assert rec is not None and rec.symbol == "RELIANCE"


def test_alias_map_symbol_not_shadowed():
    tm = load_master(UNIVERSE)
    amap = tm.alias_map()
    assert amap["RELIANCE"].symbol == "RELIANCE"
    assert amap["INFOSYS"].symbol == "INFY"

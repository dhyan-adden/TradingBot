from tradeloop.lib.data.ticker_master import load_master
from tradeloop.lib.data.tickers import extract
from tradeloop.lib.data.sources import RawItem
from pathlib import Path

TM = load_master(Path("tradeloop/config/universe.yaml"))


def _item(title, nid="deadbeef1234"):
    return RawItem(news_id=nid, title=title, url="http://x", source="google_news_generic",
                   tier="tier_C", published_at="2026-07-02T00:00:00Z")


def test_word_boundary_match_hits_full_word():
    tagged = extract([_item("Reliance posts record quarterly profit")], TM)
    assert any(t.ticker == "RELIANCE" and t.category == "earnings" for t in tagged)


def test_substring_false_positive_is_rejected():
    # legacy substring matcher tagged 'INFY' inside 'INFYMEDIA' etc.; word-boundary must not.
    tagged = extract([_item("INFYMEDIALABS launches app")], TM)
    assert all(t.ticker != "INFY" for t in tagged)


def test_short_alias_skipped():
    # a 2-char alias must never match (guards symbols like 'IT'); none of our records
    # expose a <3 char alias, so a headline of pure noise yields no tags.
    tagged = extract([_item("IT is a fine day in IN")], TM)
    assert tagged == []


def test_news_id_propagates():
    tagged = extract([_item("Infosys wins large deal", nid="cafebabe0001")], TM)
    assert tagged and tagged[0].news_id == "cafebabe0001"

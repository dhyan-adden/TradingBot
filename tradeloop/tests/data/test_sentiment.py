from tradeloop.lib.data.sentiment import score, label


def test_positive():
    assert score("Company posts strong profit and record growth") > 0
    assert label(score("strong growth beat")) == "positive"


def test_negative():
    assert score("Shares fall on fraud probe and heavy loss") < 0


def test_negation_flips():
    assert score("no profit growth this quarter") < score("profit growth this quarter")


def test_clamped():
    s = score("strong strong bullish growth profit beat up rally surge")
    assert -1.0 <= s <= 1.0


def test_empty_is_neutral():
    assert score("") == 0.0
    assert label(0.0) == "neutral"

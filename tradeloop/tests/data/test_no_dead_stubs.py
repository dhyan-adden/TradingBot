import importlib

import pytest


@pytest.mark.parametrize("mod", [
    "tradeloop.lib.data.et_markets_rss",
    "tradeloop.lib.data.moneycontrol_rss",
    "tradeloop.lib.data.corp_announcements",
    "tradeloop.lib.data.reddit_sentiment",
])
def test_dead_stub_removed(mod):
    # kills a regression where a superseded stub (replaced by sources/*) lingers importable
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(mod)

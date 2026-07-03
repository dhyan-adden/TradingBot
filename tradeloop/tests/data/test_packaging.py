import importlib


def test_feedparser_available():
    assert importlib.import_module("feedparser") is not None


def test_tradeloop_data_package_importable():
    assert importlib.import_module("tradeloop.lib.data") is not None

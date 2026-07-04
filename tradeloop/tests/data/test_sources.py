from pathlib import Path

import httpx

from tradeloop.lib.data.http import Http, DEFAULT_UA
from tradeloop.lib.data.sources import RawItem
from tradeloop.lib.data.sources.google_news import fetch_google_news
from tradeloop.lib.data.sources.rss_native import fetch_rss
from tradeloop.lib.data.sources.reddit import fetch_reddit

FX = Path("tradeloop/tests/data/fixtures")


def _http_serving(body: bytes, content_type="application/xml"):
    def handler(request):
        return httpx.Response(200, content=body, headers={"content-type": content_type})
    http = Http()
    http._client = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": DEFAULT_UA})
    return http


def test_google_news_parses_items():
    http = _http_serving((FX / "google_news.xml").read_bytes())
    items = fetch_google_news(http, "Reliance", limit=5)
    assert items and all(isinstance(i, RawItem) for i in items)
    assert items[0].tier == "tier_C"
    assert items[0].source == "google_news_generic"
    assert len(items[0].news_id) == 12


def test_rss_native_tier_and_source_label():
    http = _http_serving((FX / "moneycontrol.xml").read_bytes())
    items = fetch_rss(http, "http://feed", source="moneycontrol_news", tier="tier_B", limit=10)
    assert items and items[0].source == "moneycontrol_news" and items[0].tier == "tier_B"


def test_reddit_parses_json_listing():
    http = _http_serving((FX / "reddit.json").read_bytes(), content_type="application/json")
    items = fetch_reddit(http, ["IndianStreetBets"], limit=10)
    assert items and items[0].tier == "tier_C"
    assert items[0].source == "reddit_indianstreetbets"


def test_source_failure_returns_empty_not_raise():
    def handler(request):
        raise httpx.ConnectError("down", request=request)
    http = Http()
    http._client = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": DEFAULT_UA})
    http._sleep = lambda _s: None
    assert fetch_rss(http, "http://feed", source="mint_markets", tier="tier_A") == []

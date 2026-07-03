import httpx
import pytest

from tradeloop.lib.data.http import Http, HttpResponse, DEFAULT_UA


def _client_with(handler):
    transport = httpx.MockTransport(handler)
    http = Http()
    http._client = httpx.Client(transport=transport, headers={"User-Agent": DEFAULT_UA})
    return http


def test_get_sends_user_agent_and_returns_body():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, content=b"hello")

    http = _client_with(handler)
    resp = http.get("https://example.test/feed")
    assert isinstance(resp, HttpResponse)
    assert resp.status == 200
    assert resp.body == b"hello"
    assert seen["ua"] == DEFAULT_UA
    assert resp.not_modified is False


def test_conditional_get_sends_etag_and_flags_304():
    seen = {}

    def handler(request):
        seen["inm"] = request.headers.get("if-none-match")
        seen["ims"] = request.headers.get("if-modified-since")
        return httpx.Response(304)

    http = _client_with(handler)
    resp = http.get("https://example.test/feed", etag='"abc"', modified="Wed, 01 Jan 2026 00:00:00 GMT")
    assert seen["inm"] == '"abc"'
    assert seen["ims"] == "Wed, 01 Jan 2026 00:00:00 GMT"
    assert resp.status == 304
    assert resp.not_modified is True


def test_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, content=b"ok")

    http = _client_with(handler)
    http._sleep = lambda _s: None  # no real backoff sleep in tests
    resp = http.get("https://example.test/feed")
    assert resp.status == 200
    assert calls["n"] == 3


def test_retries_exhausted_raises():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    http = _client_with(handler)
    http._sleep = lambda _s: None
    with pytest.raises(httpx.HTTPError):
        http.get("https://example.test/feed")

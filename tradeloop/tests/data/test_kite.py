import json
from io import BytesIO
from datetime import date
from pathlib import Path

import pytest

from tradeloop.lib.data.kite import Candle, KiteAuthError, StdioTransport, KiteClient

FX = Path("tradeloop/tests/data/fixtures")


class FakeTransport:
    """Stand-in for the stdio MCP transport; maps tool name -> canned JSON result."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.responses[name]


def test_ltp_maps_symbol_to_price():
    # kills a bug where ltp() returns the raw NSE:-prefixed dict instead of a bare-symbol map
    ft = FakeTransport({"zerodha_ltp": {"NSE:INFY": {"last_price": 1500.5}}})
    kc = KiteClient(transport=ft)
    assert kc.ltp(["INFY"]) == {"INFY": 1500.5}
    assert ft.calls[0][0] == "zerodha_ltp"


def test_historical_resolves_token_then_parses_candles():
    # kills a bug where historical() skips the token lookup or mis-parses the [date,o,h,l,c,v] rows
    hist = json.loads((FX / "kite_historical.json").read_text())
    ft = FakeTransport({
        "zerodha_instrument_token": {"instrument_token": 408065},
        "zerodha_historical": hist,
    })
    kc = KiteClient(transport=ft)
    candles = kc.historical("INFY", date(2026, 6, 30), date(2026, 7, 1), "day")
    assert candles and isinstance(candles[0], Candle)
    assert candles[0].close == 1410.2
    assert ("zerodha_instrument_token", {"exchange": "NSE", "tradingsymbol": "INFY"}) in [
        (n, a) for n, a in ft.calls
    ]


def test_stdio_transport_surfaces_mcp_auth_error_without_json_decode():
    transport = StdioTransport.__new__(StdioTransport)
    transport._rpc = lambda *_a, **_k: {
        "isError": True,
        "content": [{
            "type": "text",
            "text": "Kite API 403: {\"error_type\":\"TokenException\"}",
        }],
    }

    with pytest.raises(KiteAuthError, match="Zerodha authentication failed"):
        transport.call_tool("zerodha_ltp", {"instruments": ["NSE:RELIANCE"]})


def test_stdio_transport_non_json_success_is_loud_runtime_error():
    transport = StdioTransport.__new__(StdioTransport)
    transport._rpc = lambda *_a, **_k: {
        "content": [{"type": "text", "text": "not json"}],
    }

    with pytest.raises(RuntimeError, match="returned non-JSON output"):
        transport.call_tool("zerodha_ltp", {"instruments": ["NSE:RELIANCE"]})


def test_stdio_transport_launches_mcp_from_repo_root(monkeypatch):
    captured = {}

    class FakeProc:
        stdin = BytesIO()
        stdout = BytesIO()

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return FakeProc()

    monkeypatch.setattr("tradeloop.lib.data.kite.subprocess.Popen", fake_popen)
    monkeypatch.setattr(StdioTransport, "_rpc", lambda self, method, params: {})
    monkeypatch.setattr(StdioTransport, "_notify", lambda self, method, params: None)

    StdioTransport()

    assert captured["cmd"] == ["npm", "run", "-s", "mcp:zerodha"]
    assert captured["cwd"] == str(Path(__file__).resolve().parents[3])

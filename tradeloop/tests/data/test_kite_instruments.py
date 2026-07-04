from tradeloop.lib.data.kite import KiteClient


class FakeTransport:
    def __init__(self):
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"instruments": [
            {"tradingsymbol": "RELIANCE", "instrument_token": 738561},
            {"tradingsymbol": "sbin", "instrument_token": 779521},
        ]}


def test_instruments_returns_symbol_token_map_and_seeds_cache():
    t = FakeTransport()
    k = KiteClient(transport=t)
    m = k.instruments("NSE")
    assert m == {"RELIANCE": 738561, "SBIN": 779521}  # upper-cased
    # cache seeded: resolving a token needs no second tool call
    assert k._token("RELIANCE") == 738561
    assert [c[0] for c in t.calls] == ["zerodha_instruments"]  # only the one bulk call
